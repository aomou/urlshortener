from django.contrib.auth import login
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST
from django_ratelimit.decorators import ratelimit

from .services import UserService


@require_POST
@ratelimit(key="ip", rate="1/h", block=False)
def guest_login_view(request: HttpRequest) -> HttpResponse:
    if getattr(request, "limited", False):
        return render(request, "shortener/rate_limited.html", status=429)
    user = UserService.create_guest_user()
    # 這個 guest user，用 Django 預設帳號系統登入
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return redirect("my_urls")
