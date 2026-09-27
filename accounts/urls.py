from django.urls import path

from accounts.views import RegisterCreateAPIView, CustomTokenObtainPairView, CustomTokenRefreshView, ProfileAPIView, \
    UserLookupAPIView, PublicUserAPIView

urlpatterns = [
    path('auth/register/', RegisterCreateAPIView.as_view(), name='register'),
    path('auth/login/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/token/refresh/', CustomTokenRefreshView.as_view(), name='token_refresh'),
    path('auth/profile/', ProfileAPIView.as_view(), name='profile'),
    path('users/lookup/', UserLookupAPIView.as_view(), name='user-lookup'),
    path('users/<int:pk>/', PublicUserAPIView.as_view(), name='user-detail'),
]