"""
URL configuration for core project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    # Users app 路由 -> guest login lives at /accounts/guest-login/
    path("accounts/", include("users.urls")),
    # Django-allauth OAuth 登入路由 -> Google OAuth flows
    path("accounts/", include("allauth.urls")),
    # Shortener app 路由（必須放在最後，因為有 catch-all 路由）
    path("", include("shortener.urls")),
]
