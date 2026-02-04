"""
Service 層業務邏輯實作
"""

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db.models import Count
from django_user_agents.utils import get_user_agent
from sqids import Sqids

from .exceptions import AccessDeniedError, UrlNotFoundError
from .models import ClickLog, URLModel

# 初始化 Sqids 編碼器
sqids = Sqids(min_length=6)


class URLService:
    """短網址服務"""

    @staticmethod
    def create_short_url(user, original_url):
        """
        建立短網址

        Args:
            user: Django User 物件
            original_url: 原始網址

        Returns:
            URLModel 實例

        Raises:
            ValidationError: URL 格式不正確
        """
        # 驗證 URL 格式
        validator = URLValidator()
        try:
            validator(original_url)
        except ValidationError:
            raise ValidationError("Invalid URL format") from None

        # 建立 URL 記錄（short_code 先留空）
        url_obj = URLModel.objects.create(
            user=user, original_url=original_url, short_code=""
        )

        # 使用 Sqids 編碼 user_id 和 url_id
        short_code = sqids.encode([user.id, url_obj.id])
        url_obj.short_code = short_code
        url_obj.save()

        return url_obj

    @staticmethod
    def get_url_by_code(code):
        """
        根據短碼取得 URL 物件

        Args:
            code: 短網址代碼

        Returns:
            URLModel 實例

        Raises:
            UrlNotFoundError: 短碼無效或不存在
        """
        try:
            # 解碼短碼
            decoded = sqids.decode(code)
            if len(decoded) != 2:
                raise UrlNotFoundError(f"Invalid short code: {code}")

            user_id, url_id = decoded

            # 查詢資料庫
            url_obj = URLModel.objects.get(id=url_id, user_id=user_id)
            return url_obj

        except (ValueError, URLModel.DoesNotExist):
            raise UrlNotFoundError(f"URL not found: {code}") from None

    @staticmethod
    def get_user_urls(user):
        """
        取得使用者的所有短網址

        Args:
            user: Django User 物件

        Returns:
            QuerySet of URLModel
        """
        return URLModel.objects.filter(user=user).order_by("-created_at")

    @staticmethod
    def get_user_urls_with_stats(user):
        """
        取得使用者的所有短網址（含點擊次數統計）

        Args:
            user: Django User 物件

        Returns:
            QuerySet of URLModel with click_count annotation
        """
        return (
            URLModel.objects.filter(user=user)
            .annotate(click_count=Count("clicks"))  # 使用 annotate 避免 N+1 查詢問題
            .order_by("-created_at")
        )

    @staticmethod
    def verify_owner(url_obj, user):
        """
        驗證使用者是否為 URL 擁有者

        Args:
            url_obj: URLModel 實例
            user: Django User 物件

        Raises:
            AccessDeniedError: 非擁有者
        """
        if url_obj.user != user:
            raise AccessDeniedError("You do not have permission to access this URL")


class AnalyticsService:
    """統計分析服務"""

    @staticmethod
    def record_click(url_obj, request):
        """
        記錄點擊事件

        Args:
            url_obj: URLModel 實例
            request: Django HttpRequest 物件

        Returns:
            ClickLog 實例
        """
        # 取得真實 IP（處理 Proxy/CDN）
        ip_address = AnalyticsService._get_client_ip(request)

        # 解析 User-Agent
        user_agent = get_user_agent(request)
        browser = user_agent.browser.family if user_agent.browser.family else ""
        os = user_agent.os.family if user_agent.os.family else ""
        device_type = AnalyticsService._get_device_type(user_agent)

        # 取得 Referer
        referer = request.META.get("HTTP_REFERER", "")

        # 建立點擊記錄
        click_log = ClickLog.objects.create(
            url=url_obj,
            ip_address=ip_address,
            browser=browser,
            os=os,
            device_type=device_type,
            referer=referer,
        )

        return click_log

    @staticmethod
    def get_url_stats(url_obj):
        """
        取得 URL 統計資料

        Args:
            url_obj: URLModel 實例

        Returns:
            dict: 包含統計摘要和點擊記錄
        """
        clicks = url_obj.clicks.all().order_by("-clicked_at")  # url 反向關聯到 ClickLog
        total_clicks = clicks.count()

        # 為前端顯示處理匿名化 IP
        clicks_data = []
        for click in clicks:
            clicks_data.append(
                {
                    "clicked_at": click.clicked_at,
                    "ip_address": AnalyticsService.anonymize_ip(click.ip_address),
                    "browser": click.browser,
                    "os": click.os,
                    "device_type": click.device_type,
                    "referer": click.referer,
                }
            )

        return {"total_clicks": total_clicks, "clicks": clicks_data}

    @staticmethod
    def _get_client_ip(request):
        """
        取得客戶端真實 IP 位址

        處理 Proxy/CDN 的 X-Forwarded-For Header

        Args:
            request: Django HttpRequest 物件

        Returns:
            str: IP 位址
        """
        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
        if x_forwarded_for:
            # 取第一個 IP（最接近客戶端）
            ip = x_forwarded_for.split(",")[0].strip()
        else:
            ip = request.META.get("REMOTE_ADDR")
        return ip

    @staticmethod
    def _get_device_type(user_agent):
        """
        判斷裝置類型

        Args:
            user_agent: django-user-agents UserAgent 物件

        Returns:
            str: 裝置類型
        """
        if user_agent.is_mobile:
            return "Mobile"
        elif user_agent.is_tablet:
            return "Tablet"
        elif user_agent.is_pc:
            return "PC"
        else:
            return "Unknown"

    @staticmethod
    def anonymize_ip(ip_address):
        """
        匿名化 IP 位址（用於前端顯示）

        IPv4: 遮蔽最後一段 (192.168.1.100 -> 192.168.1.0)
        IPv6: 遮蔽後 80 位元

        Args:
            ip_address: IP 位址字串

        Returns:
            str: 匿名化後的 IP
        """
        if ":" in ip_address:
            # IPv6
            parts = ip_address.split(":")
            return ":".join(parts[:4]) + "::"
        else:
            # IPv4
            parts = ip_address.split(".")
            if len(parts) == 4:
                return ".".join(parts[:3]) + ".0"
        return ip_address
