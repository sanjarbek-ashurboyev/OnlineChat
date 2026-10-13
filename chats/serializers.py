from django.db.models import Q
from drf_spectacular.utils import extend_schema_field, inline_serializer
from phonenumber_field.phonenumber import to_python
from rest_framework.exceptions import NotFound
from rest_framework.fields import (
    CharField,
    DateTimeField,
    IntegerField,
    SerializerMethodField,
)
from rest_framework.serializers import ModelSerializer, Serializer, ValidationError

from accounts.models import User
from accounts.serializers import PublicUserSerializer
from chats.models import MAX_MESSAGE_LENGTH, Block, Chat, Message


class MessageSerializer(ModelSerializer):
    sender_id = IntegerField(read_only=True)

    class Meta:
        model = Message
        fields = ['id', 'sender_id', 'text', 'created_at', 'is_read', 'read_at']
        read_only_fields = ['id', 'sender_id', 'created_at', 'is_read', 'read_at']
        extra_kwargs = {'text': {'max_length': MAX_MESSAGE_LENGTH}}


class ChatSerializer(ModelSerializer):
    participant = SerializerMethodField()
    last_message = SerializerMethodField()
    unread_count = IntegerField(read_only=True)
    # The newest of my messages the other person has read, or null. A client that missed read
    # receipts while offline repairs its ticks from this (Codex audit M-08).
    peer_read_up_to = IntegerField(read_only=True, allow_null=True)

    class Meta:
        model = Chat
        fields = ['id', 'participant', 'last_message', 'unread_count', 'peer_read_up_to', 'created_at']

    @extend_schema_field(PublicUserSerializer)
    def get_participant(self, obj):
        me = self.context['request'].user
        other = obj.user2 if obj.user1_id == me.pk else obj.user1
        data = PublicUserSerializer(other, context=self.context).data
        # Like `presence`, a list view pre-builds `blocked_by`: who among the page blocked me.
        blocked_by = self.context.get('blocked_by')
        if blocked_by is None:
            hidden = Block.objects.filter(blocker=other, blocked=me).exists()
        else:
            hidden = other.pk in blocked_by
        if hidden:
            # The profile endpoint hides them from me; the chat keeps only what I already know (M-14).
            data.update(avatar=None, is_online=False, last_seen=None)
        return data

    @extend_schema_field(inline_serializer('LastMessage', allow_null=True, fields={
        'text': CharField(), 'created_at': DateTimeField(),
    }))
    def get_last_message(self, obj):
        # Populated by Subquery in the view's queryset; None on an empty chat.
        text = getattr(obj, 'last_message_text', None)
        if text is None:
            return None
        return {'text': text, 'created_at': getattr(obj, 'last_message_at', None)}


class ReadSerializer(Serializer):
    up_to = IntegerField(min_value=0, help_text='Id of the newest message on screen; later ones stay unread.')


class ChatCreateSerializer(Serializer):
    # T-05: a phone number, not a user id. Ids are sequential, so anyone could message every user.
    phone_number = CharField(write_only=True, help_text='E.164 or local UZ format.')

    def validate_phone_number(self, value):
        me = self.context['request'].user
        number = to_python(value, region='UZ')
        if not number or not number.is_valid():
            raise ValidationError('Enter a valid phone number.')
        if number == me.phone_number:
            raise ValidationError("You can't start a chat with yourself.")

        other = User.objects.filter(phone_number=number).first()
        # A block either way is reported as a missing user, so it stays undetectable.
        if other is None or Block.objects.filter(
            Q(blocker=other, blocked=me) | Q(blocker=me, blocked=other)
        ).exists():
            raise NotFound('Nobody is registered with that number.')
        return other

    def create(self, validated_data):
        me = self.context['request'].user
        chat, _ = Chat.objects.get_or_create_chat(me, validated_data['phone_number'])
        return chat
