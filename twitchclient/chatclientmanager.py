import threading
from typing import List

from twitchclient.chatclient import ChatClient


class ChatClientManager:
    def __init__(self, oauth_password: str, nickname: str, twitch_id, logger, cluster_size=25, max_viewer_per_cluster=100):
        self.clients = []   # type: List[ChatClient]
        self.lock = threading.Lock()
        self.oauth_password = oauth_password
        self.nickname = nickname
        self.twitch_id = twitch_id
        self.logger = logger
        self.cluster_size = cluster_size
        self.max_viewer_per_cluster = max_viewer_per_cluster
        self.channel_size_dict = {}

    def _create_client(self):
        client = ChatClient(
            oauth_password=self.oauth_password, nickname=self.nickname, twitch_id=self.twitch_id, logger=self.logger
        )
        self.clients.append(client)
        return client

    def add_channel(self, channel_name: str, avg_viewer: int) -> (ChatClient, bool):
        with self.lock:
            target_client = None
            is_new = True

            for client in self.clients:
                if len(client.channel_names) < self.cluster_size:
                    if self.channel_size_dict[client] + avg_viewer < self.max_viewer_per_cluster:
                        target_client = client
                        is_new = False
                        break

            if target_client is None:
                target_client = self._create_client()

            if target_client not in self.channel_size_dict:
                self.channel_size_dict[target_client] = avg_viewer
            else:
                self.channel_size_dict[target_client] += avg_viewer

            target_client.add_channel(channel_name)

            return target_client, is_new

    def remove_channel(self, channel_name: str):
        with self.lock:
            for client in self.clients:
                client.remove_channel(channel_name)  # todo: if channel was removed remove that amount of viewers
                if len(client.channel_names) == 0:
                    self.clients.remove(client)
                    self.channel_size_dict.pop(client)
