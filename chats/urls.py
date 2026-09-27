from django.urls import path

from chats.views import ChatListCreateAPIView, MarkChatReadAPIView, MessageListCreateAPIView

urlpatterns = [
    path('chats/', ChatListCreateAPIView.as_view(), name='chat-list'),
    path('chats/<int:chat_id>/messages/', MessageListCreateAPIView.as_view(), name='message-list'),
    path('chats/<int:chat_id>/read/', MarkChatReadAPIView.as_view(), name='chat-read'),
]
