"""
Shortener app URL 配置
"""

from django.urls import path

from . import views

urlpatterns = [
    path("", views.home_view, name="home"),
    path("ping/", views.health_check, name="ping"),
    path("my-urls/", views.my_urls_view, name="my_urls"),
    path("shorten/", views.shorten_view, name="shorten"),
    path("my-urls/toggle/<int:url_id>/", views.toggle_url_view, name="toggle_url"),
    path("stats/<str:code>/", views.url_stats_view, name="url_stats"),
    # 短網址重定向必須放在最後，避免攔截其他路由
    path("<str:code>/", views.redirect_view, name="redirect"),
]
