import threading
from typing import List
from typing import Tuple
from twitchclient.chatclient import ChatClient


class ChatClientManager:
    def __init__(self, oauth_password: str, nickname: str, twitch_id, logger, max_cluster_size=50, max_viewer_per_cluster=250):
        self.clients = []   # type: List[ChatClient]
        self.clients_created = 0
        self.lock = threading.Lock()
        self.oauth_password = oauth_password
        self.nickname = nickname
        self.twitch_id = twitch_id
        self.logger = logger
        self.max_cluster_size = max_cluster_size
        self.max_viewer_per_cluster = max_viewer_per_cluster
        self.channel_size_client_dict = {}
        self.channel_size_dict = {}

    def shutdown(self):
        for client in self.clients:
            # removed so we reduce the messages sent to twitch
            # for channel_name in client.channel_names:
            #     client.remove_channel(channel_name)
            client.exit()

    def _create_client(self):
        self.clients_created += 1
        client = ChatClient(
            oauth_password=self.oauth_password, nickname=self.nickname, twitch_id=self.twitch_id, logger=self.logger, chat_client_id=self.clients_created
        )
        self.clients.append(client)
        return client

    def add_channel(self, channel_name: str, language: str, avg_viewer: int) -> Tuple[ChatClient, bool]:
        channel_name = channel_name.lower()

        with self.lock:
            target_client = None
            is_new = True

            for client in self.clients:
                if len(client.channel_names) < self.max_cluster_size:
                    if self.channel_size_client_dict[client] + avg_viewer < self.max_viewer_per_cluster:
                        target_client = client
                        is_new = False
                        break

            if target_client is None:
                target_client = self._create_client()

            if target_client not in self.channel_size_client_dict:
                self.channel_size_client_dict[target_client] = avg_viewer
            else:
                self.channel_size_client_dict[target_client] += avg_viewer

            self.channel_size_dict[channel_name] = avg_viewer
            target_client.add_channel(channel_name, language)

            return target_client, is_new

    def remove_channel(self, channel_name: str):
        channel_name = channel_name.lower()

        with self.lock:
            for client in self.clients:
                removed = client.remove_channel(channel_name)
                if removed:
                    self.channel_size_client_dict[client] -= self.channel_size_dict[channel_name]
                    self.channel_size_dict.pop(channel_name)

                if len(client.channel_names) == 0:
                    client.exit()
                    self.clients.remove(client)
                    self.channel_size_client_dict.pop(client)
