from django.contrib import admin

from .models import ClickLog, URLModel


@admin.register(URLModel)
class URLModelAdmin(admin.ModelAdmin):
    """URLModel Admin 配置"""

    list_display = ("id", "short_code", "original_url", "user", "created_at")
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
