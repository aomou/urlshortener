"""
Views 層：處理 HTTP 請求和回應
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render

from .exceptions import AccessDeniedError, UrlNotFoundError
from .services import AnalyticsService, URLService


def home_view(request):
    """
    首頁/登入頁

    顯示專案說明和第三方登入按鈕
    """
    # 如果已登入，重定向到 my-urls
    if request.user.is_authenticated:
        return redirect("my_urls")

    return render(request, "shortener/home.html")


@login_required
def my_urls_view(request):
    """
    我的網址頁

    GET: 顯示使用者的所有短網址
    POST: 建立新的短網址
    """
    if request.method == "POST":
        original_url = request.POST.get("original_url", "").strip()

        if not original_url:
            messages.error(request, "Please enter a URL")
        else:
            try:
                # 呼叫 Service 建立短網址
                url_obj = URLService.create_short_url(request.user, original_url)
                short_url = f"{request.build_absolute_uri('/')}{url_obj.short_code}/"
                messages.success(request, f"Short URL created: {short_url}")
            except ValidationError as e:
                messages.error(request, str(e))

        return redirect("my_urls")

    # GET: 顯示列表
    urls = URLService.get_user_urls_with_stats(request.user)  # 邏輯放在 service

    context = {"urls": urls}
    return render(request, "shortener/my_urls.html", context)


@login_required
def url_stats_view(request, code):
    """
    統計詳情頁

    顯示單一短網址的統計資料
    僅限擁有者訪問
    """
    try:
        # 取得 URL 物件
        url_obj = URLService.get_url_by_code(code)

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


def redirect_view(request, code):
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
