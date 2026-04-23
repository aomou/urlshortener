from django.urls import path

from . import views

urlpatterns = [
    path("guest-login/", views.guest_login_view, name="guest_login"),
]
