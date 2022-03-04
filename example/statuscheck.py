import requests

from twitchclient.chatclient import ChatClient


def init(c: ChatClient, session: requests.Session):
    logger = c.get_logger()

    @c.on_notice
    def on_notice(content: str):
        if content == "Login authentication failed":
            logger.warning("Login failed. Retrieving new token...")

            # c.oauth_password = "YOUR NEW TOKEN" # todo: GET YOUR NEW TOKEN IF AUTH FAILED
            # c.close()

        elif content.startswith(f"You are permanently banned from talking in"):
            channel_name = content.split(" ")[-1][:-1]
            logger.info(f"Bannend. Removing {channel_name} from whitelist")
        else:
            logger.warning(f"TWITCH NOTICE: {content}")
