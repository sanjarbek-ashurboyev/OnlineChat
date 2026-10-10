from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from phonenumber_field.phonenumber import to_python
from rest_framework.exceptions import ValidationError
from rest_framework.generics import (
    CreateAPIView,
    RetrieveAPIView,
    RetrieveUpdateAPIView,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from accounts.models import User
from accounts.serializers import (
    ProfileSerializer,
    PublicUserSerializer,
    RegisterSerializer,
    UserLookupSerializer,
)
from accounts.throttles import LoginIPThrottle, LoginPhoneThrottle


# Create your views here.
@extend_schema(tags=['auth'])
class RegisterCreateAPIView(CreateAPIView):
    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'register_ip'

@extend_schema(tags=['auth'])
class CustomTokenObtainPairView(TokenObtainPairView):
    throttle_classes = [LoginIPThrottle, LoginPhoneThrottle]

@extend_schema(tags=['auth'])
class CustomTokenRefreshView(TokenRefreshView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'refresh'


@extend_schema(tags=['auth'])
class ProfileAPIView(RetrieveUpdateAPIView):
    serializer_class = ProfileSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'patch', 'head', 'options']

    def get_object(self):
        return self.request.user


@extend_schema(
    tags=['users'],
    parameters=[
        OpenApiParameter('phone_number', str, required=True,
                         description='E.164 or local UZ format.'),
    ],
)
class UserLookupAPIView(RetrieveAPIView):
    serializer_class = UserLookupSerializer
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'user_lookup'

    def get_object(self):
        raw = self.request.query_params.get('phone_number')
        if not raw:
            raise ValidationError({'phone_number': 'This query parameter is required.'})

        number = to_python(raw, region='UZ')
        if not number or not number.is_valid():
            raise ValidationError({'phone_number': 'Enter a valid phone number.'})

        queryset = (
            User.objects
            .exclude(pk=self.request.user.pk)
            .exclude(blocks_made__blocked=self.request.user)
        )
        return get_object_or_404(queryset, phone_number=number)


@extend_schema(tags=['users'])
class PublicUserAPIView(RetrieveAPIView):
    serializer_class = PublicUserSerializer
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'profile_read'

    def get_queryset(self):
        return User.objects.exclude(blocks_made__blocked=self.request.user)