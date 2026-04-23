import re
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase
from django.utils import timezone

from shortener.models import ClickLog, URLModel
from shortener.services import URLService

from .services import GOOGLE_QUOTA, GOOGLE_URL_LIFETIME, GUEST_QUOTA, UserService


class UserProfileSignalTestCase(TestCase):
    """
    建立一個 User，然後檢查有沒有自動建立 UserProfile、正確的欄位初始值
    """

    def test_profile_auto_created_on_user_create(self):
        user = User.objects.create_user(
            username="testuser",
            password="testpassword",
        )

        self.assertIsNotNone(user.profile)
        self.assertEqual(user.profile.user, user)
        self.assertFalse(user.profile.is_guest)
        self.assertFalse(user.profile.is_banned)
        self.assertIsNone(user.profile.expires_at)
        self.assertIsNotNone(user.profile.created_at)


class UserServiceTestCase(TestCase):
    def test_create_guest_user(self):
        user = UserService.create_guest_user()
        self.assertTrue(re.match(r"^guest_[0-9a-f]{8}$", user.username))
        self.assertTrue(user.profile.is_guest)
        self.assertFalse(user.has_usable_password())
        # expires_at ≈ now + 24h (allow 1-minute drift)
        drift = abs((user.profile.expires_at - timezone.now()) - timedelta(hours=24))
        self.assertLess(drift.total_seconds(), 60)

    def test_get_quota(self):
        guest = UserService.create_guest_user()
        regular = User.objects.create_user(username="alice")
        admin = User.objects.create_user(username="admin", is_staff=True)
        self.assertEqual(UserService.get_quota(guest), GUEST_QUOTA)
        self.assertEqual(UserService.get_quota(regular), GOOGLE_QUOTA)
        self.assertEqual(UserService.get_quota(admin), float("inf"))

    def test_get_url_expires_at(self):
        guest = UserService.create_guest_user()
        regular = User.objects.create_user(username="alice")
        admin = User.objects.create_user(username="admin", is_staff=True)
        # Guest URL expiry 與 profile.expires_at 完全對齊
        self.assertEqual(
            UserService.get_url_expires_at(guest), guest.profile.expires_at
        )
        # Regular user 為 now + 7d（允許 1 分鐘漂移）
        drift = abs(
            (UserService.get_url_expires_at(regular) - timezone.now())
            - GOOGLE_URL_LIFETIME
        )
        self.assertLess(drift.total_seconds(), 60)
        # Admin 永不過期
        self.assertIsNone(UserService.get_url_expires_at(admin))

    def test_ban_user(self):
        user = User.objects.create_user(username="x")
        UserService.ban_user(user)
        user.refresh_from_db()
        self.assertTrue(user.profile.is_banned)


class GuestLoginViewTestCase(TestCase):
    def setUp(self):
        self.client = Client()

    def test_post_creates_guest_and_logs_in(self):
        resp = self.client.post("/accounts/guest-login/")
        self.assertRedirects(resp, "/my-urls/")
        self.assertIn("_auth_user_id", self.client.session)

    def test_get_is_method_not_allowed(self):
        resp = self.client.get("/accounts/guest-login/")
        self.assertEqual(resp.status_code, 405)


class CleanupExpiredGuestsTestCase(TestCase):
    def test_deletes_expired_guest_and_cascades(self):
        guest = UserService.create_guest_user()
        url, _ = URLService.get_or_create_short_url(guest, "https://x.com")
        ClickLog.objects.create(url=url, ip_address="1.1.1.1")
        # Backdate profile to expired
        guest.profile.expires_at = timezone.now() - timedelta(minutes=1)
        guest.profile.save()

        call_command("cleanup_expired_guests")
        self.assertFalse(User.objects.filter(pk=guest.pk).exists())
        self.assertFalse(URLModel.objects.filter(pk=url.pk).exists())
        self.assertEqual(ClickLog.objects.count(), 0)
