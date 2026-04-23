from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Delete guest users past their expires_at (cascades URLs and ClickLogs)."

    def handle(self, *args, **options):
        qs = User.objects.filter(
            profile__is_guest=True,
            profile__expires_at__lt=timezone.now(),
        )
        count = qs.count()
        qs.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {count} expired guest users"))
