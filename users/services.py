"""
User-related services: guest provisioning, quotas, URL lifetimes, banning.
"""

import secrets
from datetime import datetime, timedelta

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
    def get_url_expires_at(user: User) -> datetime | None:
        """回傳新建 URL 應設定的 expires_at（None = 永久）。"""
        if user.is_staff:
            return None
        if user.profile.is_guest:
            # 與 guest 帳號壽命完全對齊，避免 now() 漂移。
            return user.profile.expires_at
        return timezone.now() + GOOGLE_URL_LIFETIME

    @staticmethod
    def ban_user(user: User, request: HttpRequest | None = None) -> None:
        user.profile.is_banned = True
        user.profile.save(update_fields=["is_banned"])
        if request is not None:
            logout(request)
