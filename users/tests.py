from django.contrib.auth.models import User
from django.test import TestCase


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
