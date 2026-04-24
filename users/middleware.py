from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.utils import timezone


class GuestExpiryMiddleware:
    """訪客帳號過期後自動登出，避免在 cleanup 跑之前還能繼續使用。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if (
            user.is_authenticated
            and hasattr(user, "profile")
            and user.profile.is_guest
            and user.profile.expires_at
            and user.profile.expires_at < timezone.now()
        ):
            logout(request)
            messages.info(request, "Your guest session has expired.")
            return redirect("home")
        return self.get_response(request)
