"""
Service 層業務邏輯異常定義
"""


class ShortenerError(Exception):
    """短網址服務基礎異常類別"""

    pass


class UrlNotFoundError(ShortenerError):
    """短網址不存在或解碼失敗"""

    pass


class AccessDeniedError(ShortenerError):
    """權限不足，無法訪問資源"""

    pass


class UrlExpiredError(ShortenerError):
    """短網址已過期"""

    pass


class BlockedDomainError(ShortenerError):
    """目標網域在黑名單上"""

    pass


class QuotaExceededError(ShortenerError):
    """已達該使用者的 URL 配額上限"""

    pass


class UserBannedError(ShortenerError):
    """使用者已被停權"""

    pass
