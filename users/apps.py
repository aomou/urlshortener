from django.apps import AppConfig


class UsersConfig(AppConfig):
    # 指定模型預設使用的主鍵型別（auto-increment 的大整數 ID）
    default_auto_field = "django.db.models.BigAutoField"
    name = "users"

    def ready(self):
        from . import signals  # noqa F401

        # 啟動 app 時，把 signals 載進來 → 註冊所有 signal

        # signals : 某個事件發生 → 自動執行你指定的函式
        # 用來確保每個 User 都一定有對應的 UserProfile
