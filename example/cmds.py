import requests

from twitchclient.chatclient import ChatClient
from twitchclient.chatmessage import ChatMessage


def init(c: ChatClient, session: requests.Session):

    @c.on_chat_msg
    def on_chat_msg(msg: ChatMessage):
        msg_content = msg.content.lower()

        if msg_content.startswith(("!ping", "!test")):
            print("ping")
            return c.send_msg("pong", msg.channel_name)

        if msg_content.startswith(("!hello", "hi")):
            print("hello")
            return c.send_msg(f"Hello @{msg.username}", msg.channel_name)
