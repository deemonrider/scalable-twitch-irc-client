import logging
import socket
import threading
import time
import asyncio
from datetime import timedelta, datetime
from random import uniform, randint

from twitchclient.chateventhandler import ChatEventHandler
from twitchclient.chatmessage import ChatMessage


TWITCH_CHAT_MSG_LENGTH_LIMIT = 500
DEFAULT_RECONNECT_TIMEOUT = 30


class ChatModes:
    PUBLIC = "PUBLIC"
    FOLLOWER = "FOLLOWER"
    SUBSCRIBER = "SUBSCRIBER"
    EMOTE = "EMOTE"


class ChatClient(ChatEventHandler):
    def __init__(self, oauth_password: str, nickname: str, twitch_id, logger, chat_client_id=-1):
        super().__init__()
        self.chat_client_id = chat_client_id
        self.running = True
        self.logger = logger
        self.bot_logger = logging.getLogger(f"bot-detection")
        self.oauth_password = oauth_password
        self.nickname = nickname
        self.twitch_id = twitch_id
        self.users = {}
        self.sock = socket.socket()
        self.sock.settimeout(120)  # ping timeout
        self.last_connection_attempt = datetime.utcnow() - timedelta(minutes=30)
        self.channel_names = []
        self.channels = {}
        self.last_ping = time.time()
        self.chat_mode = ChatModes.PUBLIC  # todo: move the on notice to this module
        self.connection_retry_timeout = DEFAULT_RECONNECT_TIMEOUT  # in seconds
        self.pending_channels = []  # Queue to store pending channel join requests

        self.reader = None
        self.writer = None

        self.loop = asyncio.new_event_loop()

        threading.Thread(target=self.start_eventloop).start()

    def start_eventloop(self):
        asyncio.set_event_loop(self.loop)

        self.loop.run_until_complete(self.connect())

        # Schedule coroutine executions
        self.loop.create_task(self._handle_recv())
        self.loop.create_task(self._ping())
        self.loop.create_task(self.cleanup())

        # Start the event loop
        self.loop.run_forever()

    async def cleanup(self):
        i = 0
        while self.running:
            await asyncio.sleep(1)
            i += 1
            if i == 5 * 60:  # all 5 minutes
                i = 0
                time_before = (time.time() - timedelta(minutes=60).seconds)  # remove users that haven't been seen in 1 hour
                for user in self.users.copy():
                    if self.users[user]["last_active"] < time_before:
                        self.users.pop(user)
        self.logger.info(f"{self.chat_client_id}) Exiting cleanup thread gracefully.")

    async def _ping(self):
        while self.running:
            for i in range(60):  # 60 seconds
                if not self.running:  # Check if the bot is still running
                    return
                await asyncio.sleep(1)  # Sleep for 1 second

            self.send_raw("PING :tmi.twitch.tv")
            await asyncio.sleep(2)
            if time.time() - self.last_ping > 60 * 2:
                self.logger.warning(f"{self.chat_client_id}) NO PONG RECEIVED, LAST PING: {datetime.fromtimestamp(self.last_ping)}!")
                if time.time() - self.last_ping > 60 * 5:
                    self.logger.warning(f"{self.chat_client_id}) NO PONG RECEIVED FOR 5 MINUTES, RECONNECTING!")
                    await self.reconnect()
            else:
                self.logger.info(f"{self.chat_client_id}) PONG less than 2 minutes ago")
        self.logger.info(f"{self.chat_client_id}) Exiting ping thread gracefully.")

    async def rejoin_after_timeout(self, channel_name: str, timeout: int):
        await asyncio.sleep(timeout + 3)
        language = self.channels[channel_name]["language"]
        self.add_channel(channel_name, language)

    async def _handle_msg(self, msg: str):
        if msg == "PING :tmi.twitch.tv":
            self.send_raw("PONG :tmi.twitch.tv")
            self.last_ping = time.time()
            self.connection_retry_timeout = DEFAULT_RECONNECT_TIMEOUT
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
            self.logger.error(f"{self.chat_client_id}) MSG: {msg}")
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
            self.logger.error(f"{self.chat_client_id}) can't unpack cmd_s")
            self.logger.error(cmd_s)
            return

        if cmd[-1][0] == "#":
            channel_name = cmd[-1][1:]
        else:
            channel_name = None

        if len(cmd) < 2:
            self.logger.error(f"{self.chat_client_id}) len(cmd) < 2")
            return

        if cmd[1] == "JOIN":
            self.call_event_handler("join", channel_name, cmd[0].split("!")[0])
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
                self.logger.warning(f"{self.chat_client_id}) Permanently banned on channel: {channel_name}")
                self.remove_channel(channel_name)
            else:
                self.logger.warning(f"{self.chat_client_id}) Bot was timeout on channel {channel_name} for {ban_duration} seconds")
                self.remove_channel(channel_name)
                threading.Thread(target=self.rejoin_after_timeout, args=(channel_name, int(ban_duration))).start()
        elif cmd[1] == "PRIVMSG":
            chat_msg = ChatMessage(cmd[0].split("!")[0], tags.get('display-name'), tags.get("user-id"), tags.get("mod"),
                                   tags.get("color"), tags.get("badges"), tags.get("id"), content, channel_name)

            if chat_msg.user_id not in self.users:
                self.users[chat_msg.user_id] = {"antiSpam": 0, "last_active": time.time()}

            if chat_msg.content.startswith("!"):
                if self.users[chat_msg.user_id]['last_active'] > time.time() - timedelta(seconds=5).seconds:
                    self.users[chat_msg.user_id]['antiSpam'] += 1
                else:
                    if self.users[chat_msg.user_id]['antiSpam'] > 0:
                        self.users[chat_msg.user_id]['antiSpam'] -= 1

            if self.users[chat_msg.user_id]['last_active'] > time.time() - timedelta(seconds=60).seconds:
                self.users[chat_msg.user_id]['antiSpam'] = 0

            self.users[chat_msg.user_id]['channel_name'] = channel_name
            self.users[chat_msg.user_id]['username'] = chat_msg.username
            self.users[chat_msg.user_id]['last_active'] = time.time()
            self.users[chat_msg.user_id]['sub'] = "subscriber" in tags.get("badges", "") or \
                                                  "founder" in tags.get("badges", "")

            if self.users[chat_msg.user_id]['antiSpam'] < 5:
                self.call_event_handler("chat_msg", chat_msg)
        elif cmd[1].isdigit():
            self.logger.info(msg)
        else:
            self.logger.warning(msg)

    async def _handle_recv(self):
        msg = ''

        while self.running:
            while self.running:
                try:
                    data = await self.reader.readline()
                    if not data:  # Empty data means the connection was closed
                        self.logger.warning(f"{self.chat_client_id}) Connection closed by the server.")
                        break
                except ConnectionResetError as e:
                    self.logger.warning(f"{self.chat_client_id}) Twitch IRC ConnectionResetError error: {str(e)}.")
                    break
                except ConnectionAbortedError as e:
                    self.logger.warning(f"{self.chat_client_id}) Twitch IRC ConnectionAbortedError error: {str(e)}.")
                    break
                except OSError as e:
                    self.logger.warning(f"{self.chat_client_id}) Twitch IRC: Connection closed by client due to OSError: {str(e)}.")
                    break

                msg += data.decode()
                while '\n' in msg:
                    line, msg = msg.split('\n', 1)
                    await self._handle_msg(line.strip())

            await asyncio.sleep(randint(5, 60))
            self.logger.info(f"{self.chat_client_id}) Attempting to reconnect due to connection loss.")
            await self.reconnect()

    async def create_sock(self):
        self.close()
        self.sock = socket.socket()
        self.reader, self.writer = await asyncio.open_connection('irc.chat.twitch.tv', 6667)

    async def connect(self):
        self.logger.info(f"{self.chat_client_id}) Connecting to Twitch IRC...")
        try:
            await self.create_sock()
        except (TimeoutError, OSError):
            self.logger.warning(f"{self.chat_client_id}) Connection to Twitch IRC failed: {e}. Retrying...")
            await asyncio.sleep(5)
            await self.connect()
            return

        self.send_raw('CAP REQ :twitch.tv/tags twitch.tv/commands twitch.tv/membership')
        self.send_raw(f'PASS oauth:{self.oauth_password}')
        self.send_raw(f'NICK {self.nickname}')
        self.logger.info(f"{self.chat_client_id}) Connected to IRC...")

        await self.process_pending_channels()

    async def process_pending_channels(self):
        while self.pending_channels:
            channel_name, language = self.pending_channels.pop(0)
            self.add_channel(channel_name, language)

    async def reconnect(self):
        self.logger.warning(f"{self.chat_client_id}) Attempting to reconnect...")
        await asyncio.sleep(self.connection_retry_timeout)

        if not self.running:
            return
        self.logger.warning(f"{self.chat_client_id}) Performing reconnect.")

        if datetime.utcnow() - self.last_connection_attempt < timedelta(seconds=self.connection_retry_timeout):
            remaining_time = timedelta(seconds=self.connection_retry_timeout) - (datetime.utcnow() - self.last_connection_attempt)
            sleep_seconds = remaining_time.total_seconds()
            jitter = uniform(0.5, 1.5)  # Adding jitter to desynchronize reconnection attempts
            sleep_seconds *= jitter
            self.logger.warning(
                f"{self.chat_client_id}) Connection attempt denied. Please wait {sleep_seconds} seconds between attempts.")
            await asyncio.sleep(sleep_seconds)
            return

        self.logger.info(f"{self.chat_client_id}) Attempting to reconnect...")

        if self.connection_retry_timeout < 60 * 30:
            self.connection_retry_timeout *= 2

        self.last_connection_attempt = datetime.utcnow()
        await self.connect()
        await self.re_join()

    async def re_join(self):
        for channel_name in self.channel_names:
            if not self.running:
                return
            self.logger.info(f"{self.chat_client_id}) Trying to re-join #{channel_name}")
            await asyncio.sleep(3)  # prevent hitting any twitch limits
            self.send_raw(f'JOIN #{channel_name}')

    def add_channel(self, channel_name: str, language: str):
        if not self.writer:  # Check if connected
            self.logger.info(f"{self.chat_client_id}) Queuing channel #{channel_name} for joining after connection.")
            self.pending_channels.append((channel_name, language))
            return

        self.channel_names.append(channel_name)
        self.channels[channel_name] = {"chat_mode": ChatModes.PUBLIC, "language": language}
        self.logger.info(f"{self.chat_client_id}) Trying to join #{channel_name}")
        self.send_raw(f'JOIN #{channel_name}')

    def remove_channel(self, channel_name: str):
        if channel_name in self.channel_names and channel_name in self.channels:
            self.channel_names.remove(channel_name)
            self.channels.pop(channel_name)
            self.send_raw(f"PART #{channel_name}")
            return True  # success
        return False  # channel not in this cluster

    def send_raw(self, message):
        # Schedule sending message in the event loop
        self.loop.call_soon_threadsafe(asyncio.create_task, self.send_message(message))

    async def send_message(self, message):
        # Ensure we have a writer
        if not self.writer:
            return
        self.writer.write((message + '\n').encode())

        try:
            await self.writer.drain()  # Now it's safe to await drain
        except ConnectionResetError as e:
            self.logger.warning(f"{self.chat_client_id}) self.writer.drain() Twitch IRC ConnectionResetError error: {str(e)}.")
        except ConnectionAbortedError as e:
            self.logger.warning(f"{self.chat_client_id}) self.writer.drain() Twitch IRC ConnectionAbortedError error: {str(e)}.")
        except OSError as e:
            self.logger.warning(
                f"{self.chat_client_id}) self.writer.drain() Twitch IRC: Connection closed by client due to OSError: {str(e)}.")

    def send_msg(self, msg: str, channel_name: str):
        if len(msg) > TWITCH_CHAT_MSG_LENGTH_LIMIT:
            msg = msg[:TWITCH_CHAT_MSG_LENGTH_LIMIT-3] + "..."
        self.send_raw(f"PRIVMSG #{channel_name} :{msg}")

    def broadcast(self, msg: str):
        for channel_name in self.channel_names:
            self.send_msg(msg, channel_name)

    def close(self):
        if self.writer:
            try:
                self.writer.close()
                asyncio.create_task(self.writer.wait_closed())
            except Exception as e:
                self.logger.error(f"{self.chat_client_id}) Error during writer close: {e}")

        if self.sock:
            try:
                self.sock.close()
            except OSError as e:
                self.logger.error(f"{self.chat_client_id}) Error during socket close: {e}")

    def get_logger(self):
        return self.logger

    def exit(self):
        self.logger.info(f"{self.chat_client_id}) Exiting socket")
        self.running = False
        time.sleep(5)

        if self.sock:  # Check if sock exists before closing
            try:
                self.sock.shutdown(socket.SHUT_RDWR)  # Shutdown the socket before closing
            except OSError as e:
                self.logger.error(f"{self.chat_client_id}) Error during socket shutdown: {e}")
            self.close()
        self.logger.info(f"{self.chat_client_id}) Exiting the bot gracefully.")
