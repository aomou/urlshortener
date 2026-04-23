"""
Views 層：處理 HTTP 請求和回應
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django_ratelimit.decorators import ratelimit

from users.services import UserService

from .exceptions import (
    AccessDeniedError,
    BlockedDomainError,
    QuotaExceededError,
    UrlNotFoundError,
    UserBannedError,
)
from .models import URLModel
from .services import AnalyticsService, RateLimitService, URLService


def home_view(request: HttpRequest) -> HttpResponse:
    """
    首頁/登入頁

    顯示專案說明和第三方登入按鈕
    """
    # 如果已登入，重定向到 my-urls
    if request.user.is_authenticated:
        return redirect("my_urls")

    return render(request, "shortener/home.html")


@login_required
@ratelimit(key="user", rate="5/m", block=False)
def shorten_view(request: HttpRequest) -> HttpResponse:
    """
    縮短網址

    POST-only endpoint
    """
    if request.method != "POST":
        return redirect("my_urls")

    if getattr(request, "limited", False):
        RateLimitService.register_hit(request.user, request)
        # After register_hit the user might now be banned; either way show 429
        return render(request, "shortener/rate_limited.html", status=429)

    original_url = request.POST.get("original_url", "").strip()
    if not original_url:
        messages.error(request, "Please enter a URL")
        return redirect("my_urls")

    try:
        url_obj, created = URLService.get_or_create_short_url(
            request.user, original_url
        )
        short_url = f"{request.build_absolute_uri('/')}{url_obj.short_code}/"
        msg = (
            f"Short URL created: {short_url}"
            if created
            else f"You've already shortened this URL: {short_url}"
        )
        (messages.success if created else messages.warning)(request, msg)
    except ValidationError as e:
        messages.error(request, str(e))
    except BlockedDomainError:
        messages.error(request, "此網域不允許縮短")
    except QuotaExceededError as e:
        messages.error(request, str(e))
    except UserBannedError:
        from django.contrib.auth import logout as auth_logout

        auth_logout(request)
        return render(request, "users/banned.html", status=403)

    return redirect("my_urls")


@login_required
def my_urls_view(request: HttpRequest) -> HttpResponse:
    """
    我的網址頁

    GET-only endpoint 顯示使用者的所有短網址
    """
    # GET: 取得篩選參數
    status = request.GET.get("status", "all")
    sort_by = request.GET.get("sort_by", "created_at")
    order = request.GET.get("order", "desc")

    # 呼叫 Service 篩選
    urls = URLService.get_filtered_urls_with_stats(
        user=request.user,
        status_filter=status if status != "all" else None,
        sort_by=sort_by,
        sort_order=order,
    )

    now = timezone.now()
    active_count = (
        URLModel.objects.filter(user=request.user)
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .count()
    )
    quota = UserService.get_quota(request.user)

    context = {
        "urls": urls,
        "current_status": status,
        "current_sort_by": sort_by,
        "current_order": order,
        "active_count": active_count,
        "quota": quota,
        "quota_is_unlimited": quota == float("inf"),
        "url_expires_at": UserService.get_url_expires_at(request.user),
    }
    return render(request, "shortener/my_urls.html", context)


@login_required
def toggle_url_view(request: HttpRequest, url_id: int) -> HttpResponse:
    """
    切換 URL 啟用/停用狀態

    POST-only endpoint
    """
    if request.method != "POST":
        messages.error(request, "Invalid request method")
        return redirect("my_urls")

    try:
        url_obj = URLService.toggle_url_status(url_id, request.user)

        status_text = "enabled" if url_obj.is_active else "disabled"
        messages.success(request, f"URL {url_obj.short_code} has been {status_text}")

    except UrlNotFoundError:
        messages.error(request, "Short URL not found")
    except AccessDeniedError:
        messages.error(request, "You do not have permission to modify this URL")

    return redirect("my_urls")


@login_required
def url_stats_view(request: HttpRequest, code: str) -> HttpResponse:
    """
    統計詳情頁

    顯示單一短網址的統計資料
    僅限擁有者訪問
    """
    try:
        # 取得 URL 物件（不檢查 is_active，擁有者應該能查看停用 URL 的統計）
        url_obj = URLService.get_url_by_code(code, check_active=False)

        # 驗證擁有者
        URLService.verify_owner(url_obj, request.user)

        # 取得統計資料
        stats = AnalyticsService.get_url_stats(url_obj)

        context = {
            "url": url_obj,
            "total_clicks": stats["total_clicks"],
            "clicks": stats["clicks"],
            "absolute_url": request.build_absolute_uri(f"/{url_obj.short_code}/"),
        }
        return render(request, "shortener/url_stats.html", context)

    except UrlNotFoundError:  # 錯誤短網址
        messages.error(request, "Short URL not found")
        return redirect("my_urls")
    except AccessDeniedError:  # 使用者沒有權限
        messages.error(request, "You do not have permission to view this URL")
        return redirect("my_urls")


def redirect_view(request: HttpRequest, code: str) -> HttpResponse:
    """
    短網址重定向

    記錄點擊並重定向到原網址
    使用 302 暫時重定向以確保每次都經過伺服器
    """
    try:
        # 取得 URL 物件
        url_obj = URLService.get_url_by_code(code)

        # 記錄點擊
        AnalyticsService.record_click(url_obj, request)

        # 302 重定向到原網址
        return redirect(url_obj.original_url)

    except UrlNotFoundError:
        return render(request, "shortener/404.html", status=404)


def health_check(request: HttpRequest) -> JsonResponse:
    """
    健康檢查端點

    用於監控系統和 cronjob ping，保持服務活躍
    返回簡單的 JSON 回應，不需要資料庫查詢
    """
    return JsonResponse({"status": "ok"}, status=200)
