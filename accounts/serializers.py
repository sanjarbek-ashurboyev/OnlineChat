from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.fields import CharField, SerializerMethodField
from rest_framework.serializers import ModelSerializer, Serializer
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.serializers import (
    TokenObtainPairSerializer,
    TokenRefreshSerializer,
)
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.utils import datetime_from_epoch

from accounts.models import LoginSession, User
from chats import presence

MAX_AVATAR_BYTES = 2 * 1024 * 1024
MAX_AVATAR_SIDE = 4096


class RegisterSerializer(ModelSerializer):
    confirm_password = CharField(max_length=255, write_only=True)

    class Meta:
        model = User
        fields = ['phone_number', 'password', 'confirm_password', 'first_name']
        extra_kwargs = {
            'password': {'write_only': True},
        }

    def validate(self, attrs):
        if attrs['password'] != attrs['confirm_password']:
            raise ValidationError({'confirm_password': "Passwords don't match"})
        # Pass the would-be user, so the similarity check can compare the password with the name.
        candidate = User(phone_number=attrs['phone_number'], first_name=attrs.get('first_name', ''))
        try:
            validate_password(attrs['password'], user=candidate)
        except DjangoValidationError as exc:
            raise ValidationError({'password': exc.messages}) from exc
        return attrs

    def create(self, validated_data):
        validated_data.pop('confirm_password')
        try:
            # A savepoint, so a failed insert doesn't break the surrounding transaction.
            with transaction.atomic():
                return User.objects.create_user(**validated_data)
        except IntegrityError:
            # Two requests for one number can both pass the uniqueness check; the database stops the second.
            if User.objects.filter(phone_number=validated_data['phone_number']).exists():
                raise ValidationError({'phone_number': ['user with this phone number already exists.']}) from None
            raise


class ProfileSerializer(ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'first_name', 'phone_number', 'avatar',]
        read_only_fields = ['id', 'phone_number']

    def update(self, instance, validated_data):
        # Authentication may have loaded this user before another request changed their photo.
        # Reload under a row lock, and keep the lock through the save and its cleanup signals.
        with transaction.atomic():
            instance = User.objects.select_for_update().get(pk=instance.pk)
            for field, value in validated_data.items():
                setattr(instance, field, value)
            instance.save(update_fields=list(validated_data))
        return instance

    def validate_avatar(self, value):
        # Pillow only checks it's an image: a 1-pixel PNG with megabytes of junk after it passed (M-15).
        # The bytes are already received by now; a cap on the request body belongs in the proxy.
        if value is None:
            return value
        if value.size > MAX_AVATAR_BYTES:
            raise ValidationError('The photo must be 2 MiB or smaller.')
        width, height = value.image.size  # read from the header by the field's Pillow check
        if max(width, height) > MAX_AVATAR_SIDE:
            raise ValidationError(f'The photo must be at most {MAX_AVATAR_SIDE}×{MAX_AVATAR_SIDE} pixels.')
        return value


class PublicUserSerializer(ModelSerializer):
    display_name = CharField(source='first_name', read_only=True)
    is_online = SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'display_name', 'avatar', 'is_online', 'last_seen']

    def get_is_online(self, obj) -> bool:
        # A list view pre-builds `presence` in one Redis round trip; a detail
        # view has no map and asks about the single user.
        presence_map = self.context.get('presence')
        if presence_map is not None:
            return presence_map.get(obj.pk, False)
        return presence.is_online(obj.pk)


class LoginSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        return LoginSession.objects.start(user)


class SessionRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        presented = self.token_class(attrs['refresh'])
        data = super().validate(attrs)  # checks the token and the account, and makes the new pair
        renewed = self.token_class(data['refresh'], verify=False)
        # One UPDATE swaps the session's token, and only if it's still the presented one. Two requests with the same
        # token both match the row, but the database runs them one after the other: the second finds the new id and
        # changes nothing. An ended session or a token without `sid` matches nothing either.
        swapped = LoginSession.objects.filter(
            pk=presented.get('sid'), refresh_jti=presented['jti'], ended_at=None,
        ).update(refresh_jti=renewed['jti'], expires_at=datetime_from_epoch(renewed['exp']))
        if not swapped:
            raise InvalidToken('Token is no longer valid')
        return data


class LogoutSerializer(Serializer):
    refresh = CharField(write_only=True)

    def validate(self, attrs):
        # Any refresh token of the login will do, even one already renewed: another tab may have renewed it.
        token = RefreshToken(attrs['refresh'])
        LoginSession.objects.filter(pk=token.get('sid'), ended_at=None).update(ended_at=timezone.now())
        return {}
