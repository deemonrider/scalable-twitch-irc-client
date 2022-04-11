import logging
import socket
import threading
import time
from datetime import timedelta

from twitchclient.chateventhandler import ChatEventHandler
from twitchclient.chatmessage import ChatMessage


class ChatModes:
    PUBLIC = "PUBLIC"
    FOLLOWER = "FOLLOWER"
    SUBSCRIBER = "SUBSCRIBER"
    EMOTE = "EMOTE"


class ChatClient(ChatEventHandler):
    def __init__(self, oauth_password: str, nickname: str, twitch_id, logger):
        super().__init__()
        self.running = True
        self.lock = threading.Lock()
        self.logger = logger
        self.bot_logger = logging.getLogger(f"bot-detection")
        self.msg_queue = []
        self.oauth_password = oauth_password
        self.nickname = nickname
        self.twitch_id = twitch_id
        self.users = {}
        self.sock = socket.socket()
        self.sock.settimeout(120)   # ping timeout
        self.connect()
        self.reconnect_count = 0    # prevent multiple reconnects at the same time
        self.channel_names = []
        self.channels = {}
        self.last_ping = time.time()
        self.chat_mode = ChatModes.PUBLIC # todo: move the on notice to this module
        threading.Thread(target=self._handle_recv).start()
        threading.Thread(target=self._ping).start()

    def get_logger(self):
        return self.logger

    def _ping(self):
        while self.running:
            time.sleep(60)
            self.send_raw("PING :tmi.twitch.tv")
            time.sleep(2)
            if time.time() - self.last_ping > 60 * 2:
                self.logger.warning("NO PONG RECEIVED, RECONNECTING!")
                self.reconnect()

    def _handle_msg(self, msg: str):
        if msg == "PING :tmi.twitch.tv":
            self.send_raw("PONG :tmi.twitch.tv")
            self.last_ping = time.time()
            return
        elif msg == ":tmi.twitch.tv PONG tmi.twitch.tv :tmi.twitch.tv":
            self.last_ping = time.time()
            return
        if msg.count(":") < 2:
            msg += " :"  # empty content
        if msg.startswith(":"):
            msg = " " + msg
        try:
            tags_s, cmd_s, content = [x.strip() for x in msg.split(" :", 2)]
        except ValueError:
            self.logger.error(f"MSG: {msg}")
            return

        # parse tags
        tags = {}
        if tags_s:
            for t in tags_s[1:].split(";"):  # type: str
                key, val = t.split("=", 1)
                tags[key] = val

        # handle msg
        try:
            cmd = cmd_s.split(" ")
        except ValueError:
            self.logger.error("can't unpack cmd_s")
            self.logger.error(cmd_s)
            return

        if cmd[-1][0] == "#":
            channel_name = cmd[-1][1:]
        else:
            channel_name = None

        if len(cmd) < 2:
            self.logger.error("len(cmd) < 2")
            return

        if cmd[1] == "JOIN":
            self.call_event_handler("join", channel_name, cmd[0].split("!")[0])
        elif cmd[1] == "WHISPER":
            pass
        elif cmd[1] == "CAP" or cmd[1] == "GLOBALUSERSTATE" or cmd[1] == "USERSTATE":
            pass
        elif cmd[1] == "NOTICE":
            self.call_event_handler("notice", content)
        elif cmd[1] == "ROOMSTATE":
            try:
                if tags.get('subs-only') == "1":
                    self.channels[channel_name]["chat_mode"] = ChatModes.SUBSCRIBER
                elif tags.get('emote-only') == "1":
                    self.channels[channel_name]["chat_mode"] = ChatModes.EMOTE
                elif tags.get('followers-only') == "-1":
                    self.channels[channel_name]["chat_mode"] = ChatModes.PUBLIC
                else:
                    self.channels[channel_name]["chat_mode"] = ChatModes.FOLLOWER
            except KeyError:
                pass
        elif cmd[1] == "CLEARCHAT":
            target_user = tags.get("target-user-id")
            if target_user != self.twitch_id:
                return

            ban_duration = tags.get("ban-duration", 0)
            if ban_duration == 0:
                self.logger.warning(f"Permanently banned on channel: {channel_name}")
                self.remove_channel(channel_name)
            else:
                self.logger.warning(f"Bot was timeout on channel {channel_name} for {ban_duration} seconds")
                self.remove_channel(channel_name)
        elif cmd[1] == "PRIVMSG":
            chat_msg = ChatMessage(cmd[0].split("!")[0], tags.get('display-name'), tags.get("user-id"), tags.get("mod"),
                                   tags.get("color"), tags.get("badges"), tags.get("id"), content, channel_name)
            if chat_msg.user_id not in self.users:
                self.users[chat_msg.user_id] = {"antiSpam": 0, "last_active": time.time()}

            if chat_msg.content.startswith("!"):
                if self.users[chat_msg.user_id]['last_active'] > time.time() - timedelta(seconds=5).seconds:
                    self.users[chat_msg.user_id]['antiSpam'] += 1
                elif self.users[chat_msg.user_id]['last_active'] < time.time() - timedelta(seconds=360).seconds:
                    self.users[chat_msg.user_id]['antiSpam'] = 0
                else:
                    if self.users[chat_msg.user_id]['antiSpam'] > 0:
                        self.users[chat_msg.user_id]['antiSpam'] -= 1

            self.users[chat_msg.user_id]['channel_name'] = channel_name
            self.users[chat_msg.user_id]['username'] = chat_msg.username
            self.users[chat_msg.user_id]['last_active'] = time.time()
            self.users[chat_msg.user_id]['sub'] = "subscriber" in tags.get("badges", "") or \
                                                  "founder" in tags.get("badges", "")

            if self.users[chat_msg.user_id]['antiSpam'] < 7:
                self.call_event_handler("chat_msg", chat_msg)
        elif cmd[1].isdigit():
            self.logger.info(msg)
        else:
            self.logger.warning(msg)

    def _handle_recv(self):
        msg = b''
        while self.running:
            while self.running:
                try:
                    data = self.sock.recv(1)
                except (ConnectionAbortedError, ConnectionResetError, OSError):
                    self.logger.warning("Twitch IRC: Connection closed by client.")
                    break
                if not data:
                    self.logger.warning("Twitch IRC: Connection closed by server.")
                    break
                if data == b'\n':
                    self._handle_msg(msg.decode().strip())
                    msg = b''
                else:
                    msg += data
            self.reconnect()

    def create_sock(self):
        self.close()
        self.sock = socket.socket()
        self.sock.settimeout(120)  # ping timeout

    def connect(self):
        self.logger.info("Connecting to Twitch IRC...")
        try:
            self.sock.connect(('irc.chat.twitch.tv', 6667))
        except (TimeoutError, socket.timeout, OSError):
            self.logger.warning('Connection to Twitch IRC failed... Retrying')
            time.sleep(5)
            self.create_sock()
            return self.connect()
        self.send_raw('CAP REQ :twitch.tv/tags twitch.tv/commands twitch.tv/membership', False)
        self.send_raw(f'PASS oauth:{self.oauth_password}', False)
        self.send_raw(f'NICK {self.nickname}', False)
        self.logger.info("Connected to IRC...")

    def reconnect(self):
        if not self.running:
            return

        old_reconnect_count = self.reconnect_count
        with self.lock:
            if old_reconnect_count != self.reconnect_count:
                return
            self.reconnect_count += 1
            self.create_sock()
            self.connect()
            self.re_join()

    def re_join(self):
        for channel_name in self.channel_names:
            self.logger.info(f"Trying to re-join #{channel_name}")
            self.send_raw(f'JOIN #{channel_name}', lock=False)

    def add_channel(self, channel_name: str):
        with self.lock:
            self.channel_names.append(channel_name)
            self.channels[channel_name] = {"chat_mode": ChatModes.PUBLIC}
            self.logger.info(f"Trying to join #{channel_name}")
            self.send_raw(f'JOIN #{channel_name}', lock=False)

    def remove_channel(self, channel_name: str):
        with self.lock:
            if channel_name in self.channel_names:
                self.channel_names.remove(channel_name)
                self.channels.pop(channel_name)
                self.send_raw(f"PART #{channel_name}", lock=False)

    def send_raw(self, msg: str, lock=True):
        if lock:
            self.lock.acquire()
        try:
            self.sock.send(f"{msg}\n".encode())
        except OSError as e:
            self.logger.warning("Twitch IRC: Connection closed while sending.")
            self.logger.error(e)
            threading.Thread(target=self.reconnect).start()     # make sure the current reconnect call releases the lock
        if lock:
            self.lock.release()

    def send_msg(self, msg: str, channel_name: str):
        if len(msg) > 500:
            msg = msg[:497] + "..."
        self.send_raw(f"PRIVMSG #{channel_name} :{msg}")

    def broadcast(self, msg: str):
        for channel_name in self.channel_names:
            self.send_msg(msg, channel_name)

    def close(self):
        """ Automatically reconnects """
        self.sock.close()

    def exit(self):
        self.logger.info("exiting socket")
        self.running = False
        time.sleep(3)
        self.close()