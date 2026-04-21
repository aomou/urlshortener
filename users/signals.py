from django.conf import settings
from django.db.models.signals import post_save  # 資料儲存後被觸發
from django.dispatch import receiver

from .models import UserProfile

# 註冊 signal handler
# 當 User model 被 save 時，呼叫下面這個 func


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)
