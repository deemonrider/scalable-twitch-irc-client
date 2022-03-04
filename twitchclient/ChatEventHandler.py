import threading
from typing import Callable, Any

from twitchclient.ChatMessage import ChatMessage


class ChatEventHandler:
    def __init__(self):
        self.event_handlers = {}
        self.event_handler_lock = threading.Lock()

    def _add_event_handler(self, name: str, handler: Callable):
        with self.event_handler_lock:
            if name not in self.event_handlers:
                self.event_handlers[name] = []
            self.event_handlers[name].append(handler)

    def call_event_handler(self, name, *args, **kwargs):
        if name in self.event_handlers:
            for func in self.event_handlers[name]:
                threading.Thread(target=func, args=args, kwargs=kwargs).start()

    def on_join(self, func: Callable[[str, str], Any]):
        self._add_event_handler("join", func)
        return func

    def on_chat_msg(self, func: Callable[[ChatMessage], Any]):
        self._add_event_handler("chat_msg", func)
        return func

    def on_notice(self, func: Callable[[str], Any]):
        self._add_event_handler("notice", func)
        return func
