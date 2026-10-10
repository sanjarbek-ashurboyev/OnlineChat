from django.db.models import Count, F, OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.generics import ListCreateAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from chats import presence
from chats.consumers import broadcast_message
from chats.models import Block, Chat, Message
from chats.serializers import ChatCreateSerializer, ChatSerializer, MessageSerializer


def chats_for(user):
    """Chats the user belongs to, with participants joined in."""
    return (
        Chat.objects
        .filter(Q(user1=user) | Q(user2=user))
        .select_related('user1', 'user2')
    )


@extend_schema(tags=['chats'])
class ChatListCreateAPIView(ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = 'chat_create'

    def get_throttles(self):
        # Only starting a chat is limited; the client polls the list.
        return [ScopedRateThrottle()] if self.request.method == 'POST' else []

    def get_serializer_class(self):
        return ChatCreateSerializer if self.request.method == 'POST' else ChatSerializer

    def get_queryset(self):
        me = self.request.user
        latest = Message.objects.filter(chat=OuterRef('pk')).order_by('-created_at')
        return (
            chats_for(me)
            .annotate(
                last_message_text=Subquery(latest.values('text')[:1]),
                last_message_at=Subquery(latest.values('created_at')[:1]),
                unread_count=Count(
                    'messages',
                    filter=Q(messages__is_read=False) & ~Q(messages__sender=me),
                ),
            )
            .order_by(F('last_message_at').desc(nulls_last=True), '-created_at')
        )

    def other_party_ids(self, chats):
        me_pk = self.request.user.pk
        return [c.user2_id if c.user1_id == me_pk else c.user1_id for c in chats]

    def list(self, request, *args, **kwargs):
        # One Redis round trip for the whole page, rather than one per chat.
        page = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        context = {
            **self.get_serializer_context(),
            'presence': presence.online_map(self.other_party_ids(page)),
        }
        serializer = ChatSerializer(page, many=True, context=context)
        return self.get_paginated_response(serializer.data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        chat = serializer.save()
        # Re-fetch through get_queryset so the annotations are present.
        output = ChatSerializer(
            self.get_queryset().get(pk=chat.pk),
            context=self.get_serializer_context(),
        )
        return Response(output.data, status=201)


@extend_schema(tags=['chats'])
@extend_schema_view(get=extend_schema(parameters=[
    OpenApiParameter('after', int, description='Only messages with a larger id, oldest first. '
                     'Used after a reconnect to fetch what the socket missed.'),
]))
class MessageListCreateAPIView(ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MessageSerializer

    def get_chat(self):
        return get_object_or_404(chats_for(self.request.user),
                                 pk=self.kwargs['chat_id'])

    def get_queryset(self):
        messages = self.get_chat().messages
        after = self.request.query_params.get('after')
        if after is None:
            # Newest first, so page 1 is what the chat window actually shows.
            # The client reverses for display and pages backwards for history.
            return messages.order_by('-created_at')

        # ?after=<id>: what a reconnecting client missed (COR-1), oldest first.
        try:
            after = int(after)
        except ValueError:
            after = -1
        if after < 0:
            raise ValidationError({'after': 'Must be a message id.'})
        return messages.filter(id__gt=after).order_by('id')

    def perform_create(self, serializer):
        me = self.request.user
        chat = self.get_chat()
        other = chat.user2 if chat.user1_id == me.pk else chat.user1

        blocked = Block.objects.filter(
            Q(blocker=other, blocked=me) | Q(blocker=me, blocked=other)
        ).exists()
        if blocked:
            raise PermissionDenied("You can't send messages in this chat.")

        message = serializer.save(chat=chat, sender=me)
        broadcast_message(message, chat=chat)


@extend_schema(tags=['chats'], request=None, responses={200: None})
class MarkChatReadAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, chat_id):
        chat = get_object_or_404(chats_for(request.user), pk=chat_id)
        updated = (
            chat.messages
            .filter(is_read=False)
            .exclude(sender=request.user)
            .update(is_read=True, read_at=timezone.now())
        )
        return Response({'marked_read': updated})
