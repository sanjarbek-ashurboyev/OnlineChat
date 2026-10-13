from django.urls import path

from accounts.views import (
    CustomTokenObtainPairView,
    CustomTokenRefreshView,
    LogoutView,
    ProfileAPIView,
    PublicUserAPIView,
    RegisterCreateAPIView,
)

urlpatterns = [
    path('auth/register/', RegisterCreateAPIView.as_view(), name='register'),
    path('auth/login/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/token/refresh/', CustomTokenRefreshView.as_view(), name='token_refresh'),
    path('auth/logout/', LogoutView.as_view(), name='logout'),
    path('auth/profile/', ProfileAPIView.as_view(), name='profile'),
    path('users/<int:pk>/', PublicUserAPIView.as_view(), name='user-detail'),
]