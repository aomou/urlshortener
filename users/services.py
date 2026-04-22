"""
User-related services: guest provisioning, quotas, URL lifetimes, banning.
"""

import secrets
from datetime import timedelta

from django.contrib.auth import logout
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.http import HttpRequest
from django.utils import timezone

GUEST_QUOTA = 5
GOOGLE_QUOTA = 10
GUEST_LIFETIME = timedelta(hours=24)
GOOGLE_URL_LIFETIME = timedelta(days=7)


class UserService:
    @staticmethod
    def create_guest_user() -> User:
        """建立訪客帳號，自動產生 username 並設定 24h 過期。"""
        for _ in range(3):  # retry on the extremely unlikely collision
            username = f"guest_{secrets.token_hex(4)}"
            try:
                with transaction.atomic():
                    user = User.objects.create(username=username, email="")
                    user.set_unusable_password()
                    user.save()
                    profile = user.profile  # auto-created via signal
                    profile.is_guest = True
                    profile.expires_at = timezone.now() + GUEST_LIFETIME
                    profile.save()
                    return user
            except IntegrityError:
                continue
        raise RuntimeError("Failed to allocate a unique guest username after 3 tries")

    @staticmethod
    def get_quota(user: User) -> int | float:
        if user.is_staff:
            return float("inf")
        if user.profile.is_guest:
            return GUEST_QUOTA
        return GOOGLE_QUOTA

    @staticmethod
    def get_url_lifetime(user: User) -> timedelta | None:
        if user.is_staff:
            return None
        if user.profile.is_guest:
            # Align URL expiry with the guest account's own expiry.
            return user.profile.expires_at - timezone.now()
        return GOOGLE_URL_LIFETIME

    @staticmethod
    def ban_user(user: User, request: HttpRequest | None = None) -> None:
        user.profile.is_banned = True
        user.profile.save(update_fields=["is_banned"])
        if request is not None:
            logout(request)
