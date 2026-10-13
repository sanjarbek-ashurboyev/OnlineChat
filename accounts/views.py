from drf_spectacular.utils import extend_schema
from rest_framework.generics import (
    CreateAPIView,
    RetrieveAPIView,
    RetrieveUpdateAPIView,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.views import (
    TokenBlacklistView,
    TokenObtainPairView,
    TokenRefreshView,
)

from accounts.models import User
from accounts.serializers import (
    ProfileSerializer,
    PublicUserSerializer,
    RegisterSerializer,
)
from accounts.throttles import (
    LoginIPThrottle,
    LoginPhoneThrottle,
    RegisterIPThrottle,
    ScopedRateThrottle,
)


# Create your views here.
@extend_schema(tags=['auth'])
class RegisterCreateAPIView(CreateAPIView):
    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer
    throttle_classes = [RegisterIPThrottle]

@extend_schema(tags=['auth'])
class CustomTokenObtainPairView(TokenObtainPairView):
    throttle_classes = [LoginIPThrottle, LoginPhoneThrottle]

@extend_schema(tags=['auth'])
class CustomTokenRefreshView(TokenRefreshView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'refresh'

@extend_schema(tags=['auth'])
class LogoutView(TokenBlacklistView):
    """Blacklists the refresh token. Needs no access token: it may have expired, and the refresh token is the proof."""
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'refresh'


@extend_schema(tags=['auth'])
class ProfileAPIView(RetrieveUpdateAPIView):
    serializer_class = ProfileSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'patch', 'head', 'options']

    def get_object(self):
        return self.request.user


@extend_schema(tags=['users'])
class PublicUserAPIView(RetrieveAPIView):
    serializer_class = PublicUserSerializer
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'profile_read'

    def get_queryset(self):
        return User.objects.exclude(blocks_made__blocked=self.request.user)