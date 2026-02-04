"""
Shortener app URL 配置
"""

from django.urls import path

from . import views

urlpatterns = [
    path("", views.home_view, name="home"),
    path("my-urls/", views.my_urls_view, name="my_urls"),
    path("stats/<str:code>/", views.url_stats_view, name="url_stats"),
    # 短網址重定向必須放在最後，避免攔截其他路由
    path("<str:code>/", views.redirect_view, name="redirect"),
]
