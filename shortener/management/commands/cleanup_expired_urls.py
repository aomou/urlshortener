from django.core.management.base import BaseCommand
from django.utils import timezone

from shortener.models import URLModel


class Command(BaseCommand):
    help = "Delete URLs whose expires_at is in the past (cascades ClickLogs)."

    def handle(self, *args, **options):
        deleted, _ = URLModel.objects.filter(expires_at__lt=timezone.now()).delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} expired URLs"))
