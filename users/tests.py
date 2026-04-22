import re
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

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

    def test_get_url_lifetime(self):
        guest = UserService.create_guest_user()
        regular = User.objects.create_user(username="alice")
        admin = User.objects.create_user(username="admin", is_staff=True)
        # Guest lifetime is a bit less than 24h (time has passed since creation)
        self.assertLess(UserService.get_url_lifetime(guest), timedelta(hours=24))
        self.assertGreater(
            UserService.get_url_lifetime(guest), timedelta(hours=23, minutes=59)
        )
        self.assertEqual(UserService.get_url_lifetime(regular), GOOGLE_URL_LIFETIME)
        self.assertIsNone(UserService.get_url_lifetime(admin))

    def test_ban_user(self):
        user = User.objects.create_user(username="x")
        UserService.ban_user(user)
        user.refresh_from_db()
        self.assertTrue(user.profile.is_banned)
