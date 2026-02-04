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
