import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.users.manager import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    first_name = models.CharField(max_length=50, blank=False)
    last_name = models.CharField(max_length=50, blank=False)
    middle_name = models.CharField(max_length=50, blank=True, default="")
    user_name = models.CharField(max_length=50, unique=True, blank=False)
    # Optional; NULL (not "") when unknown so the unique index allows many.
    phone = models.CharField(max_length=50, unique=True, null=True, blank=True)
    profile_picture = models.CharField(max_length=255, null=True)
    email = models.EmailField(_("email address"), unique=True)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    # False while an invited user hasn't accepted the invite (set a password).
    is_verified = models.BooleanField(default=True)
    previous_passwords = models.TextField(blank=True, default="")
    timezone = models.CharField(max_length=50, default="UTC")
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        db_table = "users"

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def is_pending(self) -> bool:
        """Invited but hasn't set a password yet."""
        return not self.is_verified

    def get_previous_passwords(self):
        return self.previous_passwords.split(",")


class AccountToken(models.Model):
    """A one-time link for accepting an invite or resetting a password.

    Only a SHA-256 of the token is stored; the raw token exists only in the
    link handed to the user, so a database leak can't be replayed.
    """

    class Purpose(models.TextChoices):
        INVITE = "INVITE"
        PASSWORD_RESET = "PASSWORD_RESET"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="account_tokens",
    )
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    token_hash = models.CharField(max_length=64, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "account_tokens"
        indexes = [models.Index(fields=["user", "purpose", "used_at"])]

    def __str__(self):
        return f"{self.purpose} for {self.user_id}"

    @property
    def is_usable(self) -> bool:
        return self.used_at is None and self.expires_at > timezone.now()
