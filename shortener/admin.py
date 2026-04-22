from django.contrib import admin

from .models import ClickLog, RateLimitEvent, URLModel


@admin.register(URLModel)
class URLModelAdmin(admin.ModelAdmin):
    """URLModel Admin 配置"""

    list_display = (
        "id",
        "short_code",
        "original_url",
        "user",
        "is_active",
        "created_at",
    )
    list_filter = ("is_active", "created_at", "user")
    search_fields = ("short_code", "original_url", "user__username")
    readonly_fields = ("id", "short_code", "created_at")


@admin.register(ClickLog)
class ClickLogAdmin(admin.ModelAdmin):
    """ClickLog Admin 配置"""

    list_display = (
        "id",
        "url",
        "clicked_at",
        "ip_address",
        "browser",
        "os",
        "device_type",
    )
    search_fields = ("url__short_code", "ip_address")
    readonly_fields = ("id", "clicked_at")


@admin.register(RateLimitEvent)
class RateLimitEventAdmin(admin.ModelAdmin):
    """RateLimitEvent Admin 配置"""

    list_display = ("user", "created_at")
    list_filter = ("created_at",)
    search_fields = ("user__username",)
    readonly_fields = ("user", "created_at")
