from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import AbstractUser
from django.db.models import (
    CASCADE,
    CharField,
    DateTimeField,
    ForeignKey,
    ImageField,
    Manager,
    Model,
)
from phonenumber_field.modelfields import PhoneNumberField
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.utils import datetime_from_epoch


# Create your models here.
class CustomUserManager(BaseUserManager):
    def _create_user_object(self, phone_number, password, **extra_fields):
        if not phone_number:
            raise ValueError("The given phone number must be set")
        user = self.model(phone_number=phone_number, **extra_fields)
        user.password = make_password(password)
        return user

    def _create_user(self, phone_number, password, **extra_fields):
        user = self._create_user_object(phone_number, password, **extra_fields)
        user.save(using=self._db)
        return user

    def create_user(self, phone_number, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(phone_number, password, **extra_fields)

    def create_superuser(self, phone_number, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(phone_number, password, **extra_fields)


class User(AbstractUser):
    phone_number = PhoneNumberField(unique=True, region="UZ")
    # is_online = BooleanField(default=False)
    last_seen = DateTimeField(null=True, blank=True)
    avatar = ImageField(upload_to='avatars/', null=True, blank=True)

    username = None
    email = None
    USERNAME_FIELD = 'phone_number'
    REQUIRED_FIELDS = []
    objects = CustomUserManager()

    def __str__(self):
        return str(self.phone_number)



    


class LoginSessionManager(Manager):
    def start(self, user):
        """The refresh token of a new login. Its `sid` claim names the session and survives every rotation."""
        token = RefreshToken.for_user(user)
        session = self.create(user=user, refresh_jti=token['jti'], expires_at=datetime_from_epoch(token['exp']))
        token['sid'] = session.pk
        return token


class LoginSession(Model):
    """One login: one browser or device. Its refresh token changes on every refresh; the session stays.

    Only the refresh token whose id is `refresh_jti` works, so each one works once. Logout sets `ended_at` and
    ends the login whichever of its tokens the client still had.
    """
    user = ForeignKey(User, on_delete=CASCADE, related_name='login_sessions')
    refresh_jti = CharField(max_length=255)
    created_at = DateTimeField(auto_now_add=True)
    expires_at = DateTimeField()
    ended_at = DateTimeField(null=True, blank=True)

    objects = LoginSessionManager()
