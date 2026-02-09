"""
Service 層業務邏輯實作
"""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db.models import Count, Q
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
    def get_or_create_short_url(user, original_url):
        """
        取得或建立短網址（防止重複）

        檢查使用者是否已經為相同的 URL 建立過短網址。
        如果已存在，返回現有短網址；否則建立新的短網址。

        Args:
            user: Django User 物件
            original_url: 原始網址

        Returns:
            tuple: (url_obj, created)
                - url_obj: URLModel 實例
                - created: bool - True 表示新建立，False 表示已存在

        Raises:
            ValidationError: URL 格式不正確
        """
        # 驗證 URL 格式
        validator = URLValidator()
        try:
            validator(original_url)
        except ValidationError:
            raise ValidationError("Invalid URL format") from None

        # 查詢是否已存在相同的 (user, original_url) 組合
        existing_url = URLModel.objects.filter(
            user=user, original_url=original_url
        ).first()

        # 如果已存在，返回現有 URL
        if existing_url:
            return (existing_url, False)

        # 如果不存在，呼叫原有的 create_short_url 建立新 URL
        new_url = URLService.create_short_url(user, original_url)
        return (new_url, True)

    @staticmethod
    def get_url_by_code(code, check_active=True):
        """
        根據短碼取得 URL 物件

        Args:
            code: 短網址代碼
            check_active: 是否檢查 URL 啟用狀態（預設 True）

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

            # 檢查 URL 是否啟用（僅在 check_active=True 時）
            if check_active and not url_obj.is_active:
                raise UrlNotFoundError(f"URL is inactive: {code}")

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
    def get_filtered_urls_with_stats(
        user, status_filter=None, sort_by="created_at", sort_order="desc"
    ):
        """
        取得使用者的篩選過的 URL 列表（含統計）

        Args:
            user: Django User 物件
            status_filter: 狀態篩選 ('active', 'inactive', None 表示全部)
            sort_by: 排序欄位 ('created_at', 'original_url')
            sort_order: 排序方向 ('asc' 升序, 'desc' 降序)

        Returns:
            QuerySet of URLModel with click_count annotation
        """
        # 基礎查詢
        queryset = URLModel.objects.filter(user=user)

        # 狀態篩選
        if status_filter == "active":
            queryset = queryset.filter(is_active=True)
        elif status_filter == "inactive":
            queryset = queryset.filter(is_active=False)

        # 加入點擊統計
        queryset = queryset.annotate(click_count=Count("clicks"))

        # 排序
        sort_field = "original_url" if sort_by == "original_url" else "created_at"
        order_prefix = "-" if sort_order == "desc" else ""
        queryset = queryset.order_by(f"{order_prefix}{sort_field}")

        return queryset

    @staticmethod
    def toggle_url_status(url_id, user):
        """
        切換 URL 啟用狀態

        Args:
            url_id: URL 物件的 ID
            user: Django User 物件

        Returns:
            URLModel 實例（已更新狀態）

        Raises:
            UrlNotFoundError: URL 不存在
            AccessDeniedError: 使用者非擁有者
        """
        try:
            url_obj = URLModel.objects.get(id=url_id)
        except URLModel.DoesNotExist:
            raise UrlNotFoundError(f"URL not found: {url_id}") from None

        # 驗證擁有者
        URLService.verify_owner(url_obj, user)

        # 切換狀態
        url_obj.is_active = not url_obj.is_active
        url_obj.save()

        return url_obj

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
