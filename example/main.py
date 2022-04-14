import logging
import requests

from example import statuscheck, cmds
from twitchclient.chatclientmanager import ChatClientManager

OAUTH_PASSWORD = "FILL_IN"
NICKNAME = "FILL_IN"
TWITCH_ID = "FILL_IN"


def main():
    logger = logging.getLogger(f"info")

    client_manager = ChatClientManager(
        oauth_password=OAUTH_PASSWORD,
        nickname=NICKNAME,
        twitch_id=TWITCH_ID,
        logger=logger
    )

    session = requests.Session()

    # move this into a loop to join multiple channels
    c, is_new_socket = client_manager.add_channel(NICKNAME, avg_viewer=42)
    if is_new_socket:
        statuscheck.init(c, session)
        cmds.init(c, session)


if __name__ == '__main__':
    main()

