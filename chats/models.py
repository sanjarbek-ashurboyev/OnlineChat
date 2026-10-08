from django.db.models import (
    CASCADE,
    BooleanField,
    CheckConstraint,
    DateTimeField,
    F,
    ForeignKey,
    Index,
    Manager,
    Model,
    Q,
    TextField,
)

# Applied by the REST serializer and the WebSocket consumer alike. Without it one
# client could push arbitrarily large messages into the database and to every socket.
MAX_MESSAGE_LENGTH = 4000


class ChatManager(Manager):
    def get_or_create_chat(self, user_a, user_b):
        user1, user2 = sorted([user_a, user_b], key=lambda u: u.pk)
        chat, created = self.get_or_create(user1=user1, user2=user2)
        return chat, created


class Chat(Model):
    user1 = ForeignKey('accounts.User', on_delete=CASCADE, related_name='chats_as_user1')
    user2 = ForeignKey('accounts.User', on_delete=CASCADE, related_name='chats_as_user2')
    created_at = DateTimeField(auto_now_add=True)

    objects = ChatManager()

    class Meta:
        unique_together = ['user1', 'user2']
        constraints = [
            CheckConstraint(condition=Q(user1__lt=F('user2')), name='chat_users_ordered')
        ]


class Message(Model):
    chat = ForeignKey('chats.Chat', on_delete=CASCADE, related_name='messages')
    sender = ForeignKey('accounts.User', on_delete=CASCADE, related_name='sent_messages')
    text = TextField()
    created_at = DateTimeField(auto_now_add=True)
    is_read = BooleanField(default=False)
    read_at = DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['created_at']
        indexes = [
            Index(fields=['chat', 'created_at']),
        ]


class Block(Model):
    blocker = ForeignKey('accounts.User', on_delete=CASCADE, related_name='blocks_made')
    blocked = ForeignKey('accounts.User', on_delete=CASCADE, related_name='blocks_received')
    created_at = DateTimeField(auto_now_add=True)


    class Meta:
        unique_together = ['blocker', 'blocked']
        constraints = [
            CheckConstraint(condition=~Q(blocker=F('blocked')), name='cant_block_self')
        ]












