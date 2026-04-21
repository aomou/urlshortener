from django.contrib import admin

from .models import UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "is_guest", "is_banned", "expires_at", "created_at")
    list_filter = ("is_guest", "is_banned")
    search_fields = ("user__username",)
