from django.contrib.auth.models import User
from django.db import models


class URLModel(models.Model):
    """短網址資料模型"""

    id = models.AutoField(primary_key=True)
    short_code = models.CharField(
        max_length=20, unique=True, db_index=True, verbose_name="短網址代碼"
    )
    original_url = models.URLField(max_length=2048, verbose_name="原始網址")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="建立時間")
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="urls", verbose_name="擁有者"
    )

    class Meta:
        verbose_name = "短網址"
        verbose_name_plural = "短網址"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "original_url"], name="unique_user_url"
            )
        ]

    def __str__(self):
        return f"{self.short_code} -> {self.original_url}"


class ClickLog(models.Model):
    """點擊記錄資料模型"""

    url = models.ForeignKey(
        URLModel, on_delete=models.CASCADE, related_name="clicks", verbose_name="短網址"
    )
    clicked_at = models.DateTimeField(auto_now_add=True, verbose_name="點擊時間")
    ip_address = models.GenericIPAddressField(verbose_name="IP 位址")
    browser = models.CharField(max_length=50, blank=True, verbose_name="瀏覽器")
    os = models.CharField(max_length=50, blank=True, verbose_name="作業系統")
    device_type = models.CharField(max_length=50, blank=True, verbose_name="裝置類型")
    referer = models.URLField(max_length=2048, blank=True, verbose_name="來源網站")

    class Meta:
        verbose_name = "點擊記錄"
        verbose_name_plural = "點擊記錄"
        ordering = ["-clicked_at"]

    def __str__(self):
        return f"{self.url.short_code} - {self.clicked_at}"
