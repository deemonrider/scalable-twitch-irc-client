class ChatMessage:
    def __init__(self, username: str, display_name: str, user_id: str, is_mod: str,
                 color: str, badges: str, msg_id: str, content: str, channel_name: str):
        self.username = username
        self.display_name = display_name
        self.user_id = user_id
        self.is_mod = is_mod == "1"
        self.color = color
        self.badges = badges.split(",")
        self.msg_id = msg_id
        self.content = content
        self.channel_name = channel_name
