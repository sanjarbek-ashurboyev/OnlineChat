from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError
from rest_framework.fields import CharField, SerializerMethodField
from rest_framework.serializers import ModelSerializer

from accounts.models import User
from chats import presence


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


class UserLookupSerializer(ModelSerializer):
    display_name = CharField(source='first_name', read_only=True)

    class Meta:
        model = User
        fields = ['id', 'display_name', 'avatar']


class PublicUserSerializer(ModelSerializer):
    display_name = CharField(source='first_name', read_only=True)
    is_online = SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'display_name', 'avatar', 'is_online', 'last_seen']

    def get_is_online(self, obj):
        # A list view pre-builds `presence` in one Redis round trip; a detail
        # view has no map and asks about the single user.
        presence_map = self.context.get('presence')
        if presence_map is not None:
            return presence_map.get(obj.pk, False)
        return presence.is_online(obj.pk)