from drf_spectacular.utils import extend_schema
from rest_framework.generics import (
    CreateAPIView,
    RetrieveAPIView,
    RetrieveUpdateAPIView,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenViewBase,
)

from accounts.models import User
from accounts.serializers import (
    LoginSerializer,
    LogoutSerializer,
    ProfileSerializer,
    PublicUserSerializer,
    RegisterSerializer,
    SessionRefreshSerializer,
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
    serializer_class = LoginSerializer
    throttle_classes = [LoginIPThrottle, LoginPhoneThrottle]

@extend_schema(tags=['auth'])
class CustomTokenRefreshView(TokenRefreshView):
    serializer_class = SessionRefreshSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'refresh'

@extend_schema(tags=['auth'])
class LogoutView(TokenViewBase):
    """Ends the login. Needs no access token: it may have expired, and the refresh token is the proof."""
    serializer_class = LogoutSerializer
    throttle_classes = [ScopedRateThrottle]
    # Its own counter: other people's refreshes behind the same NAT must not block anyone's logout.
    throttle_scope = 'logout'


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