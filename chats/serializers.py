from django.db.models import Q
from rest_framework.fields import IntegerField, SerializerMethodField
from rest_framework.serializers import ModelSerializer, Serializer, ValidationError

from accounts.models import User
from accounts.serializers import PublicUserSerializer
from chats.models import Block, Chat, Message


class MessageSerializer(ModelSerializer):
    sender_id = IntegerField(read_only=True)

    class Meta:
        model = Message
        fields = ['id', 'sender_id', 'text', 'created_at', 'is_read', 'read_at']
        read_only_fields = ['id', 'sender_id', 'created_at', 'is_read', 'read_at']


class ChatSerializer(ModelSerializer):
    participant = SerializerMethodField()
    last_message = SerializerMethodField()
    unread_count = IntegerField(read_only=True)

    class Meta:
        model = Chat
        fields = ['id', 'participant', 'last_message', 'unread_count', 'created_at']

    def get_participant(self, obj):
        me = self.context['request'].user
        other = obj.user2 if obj.user1_id == me.pk else obj.user1
        return PublicUserSerializer(other, context=self.context).data

    def get_last_message(self, obj):
        # Populated by Subquery in the view's queryset; None on an empty chat.
        text = getattr(obj, 'last_message_text', None)
        if text is None:
            return None
        return {'text': text, 'created_at': getattr(obj, 'last_message_at', None)}


class ChatCreateSerializer(Serializer):
    participant_id = IntegerField(write_only=True)

    def validate_participant_id(self, value):
        me = self.context['request'].user
        if value == me.pk:
            raise ValidationError("You can't start a chat with yourself.")

        blocked = Block.objects.filter(
            Q(blocker_id=value, blocked=me) | Q(blocker=me, blocked_id=value)
        )
        # A block is reported as a missing user so it stays undetectable.
        if not User.objects.filter(pk=value).exists() or blocked.exists():
            raise ValidationError('No such user.')
        return value

    def create(self, validated_data):
        me = self.context['request'].user
        other = User.objects.get(pk=validated_data['participant_id'])
        chat, _ = Chat.objects.get_or_create_chat(me, other)
        return chat
