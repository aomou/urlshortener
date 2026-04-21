from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )

    is_guest = models.BooleanField(default=False)
    is_banned = models.BooleanField(default=False)

    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        role = "guest" if self.is_guest else ("baned" if self.is_banned else "user")
        return f"{self.user.username} ({role})"
