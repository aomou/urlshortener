# API Endpoint + Telegram Bot 對接架構 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 為 Django URL shortener 新增 token-authenticated JSON API（`POST /api/v1/shorten/`、`GET /api/v1/urls/`、`GET /api/v1/stats/<code>/`），讓 Telegram bot（之後另開 spec）能以 polling 模式呼叫。

**Architecture:** 沿用既有 service 層（`URLService` / `AnalyticsService` / `RateLimitService`）；新增 `ApiToken` model（multi-token per user、SHA-256 hash 儲存）+ `require_api_token` decorator + thin API views + helper modules（serializer / error envelope）。Web view（session auth）與 API view（token auth）並存互不影響。

**Tech Stack:** Django 6.0、Django Admin、`django-ratelimit`、`hashlib.sha256`、`secrets.token_urlsafe`。**不引入** DRF、不引入 pydantic（spec §2 non-goals）。

**Reference spec:** `doc/specs/2026-04-30-api-and-tg-bot-design.md`

---

## File Structure

| 動作 | 檔案 | 用途 |
|---|---|---|
| Modify | `shortener/models.py` | 加 `ApiToken` model + `issue()` classmethod |
| New | `shortener/migrations/0006_apitoken.py` | auto-generated |
| Modify | `shortener/admin.py` | 註冊 `ApiTokenAdmin`，覆寫 `save_model` 顯示 plaintext 一次 |
| New | `shortener/api_errors.py` | `api_error()` helper + `ErrorCode` constants |
| New | `shortener/api_auth.py` | `require_api_token` decorator |
| New | `shortener/api_serializers.py` | `serialize_url`、`serialize_url_list` |
| New | `shortener/api_views.py` | 3 個 API view function |
| New | `shortener/api_urls.py` | API URL 路由 |
| Modify | `core/urls.py` | 在 catch-all 之前掛 `/api/v1/` |
| Modify | `shortener/tests.py` | 新增 API 相關測試章節 |

**測試慣例（既有專案 pattern）：**
- 單一 `shortener/tests.py`，以 `# === Section ===` comment 分區
- 用 Django `TestCase` + `RequestFactory` / `Client`（不用 pytest）
- 跑指令：`python manage.py test shortener -v 2`

**Git commits：** 使用者偏好手動 commit（已記在 memory）。每個 Task 結尾為「Stop for user to review/commit」，不自動 `git commit`。

---

## Task 1: Add `ApiToken` model + migration

**Files:**
- Modify: `shortener/models.py`
- Create: `shortener/migrations/0006_apitoken.py` (auto-generated)
- Modify: `shortener/tests.py`

- [ ] **Step 1: Write failing tests for `ApiToken` model**

Append to `shortener/tests.py` (新章節，放在 file 最末或 model 區塊下方)：

```python
# ============================================================
# ApiToken Model
# ============================================================
import hashlib
from shortener.models import ApiToken


class ApiTokenModelTestCase(TestCase):
    """ApiToken model + issue() classmethod 測試"""

    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="x")

    def test_issue_returns_obj_and_plaintext(self):
        """issue() 應該回傳 (token_obj, plaintext) tuple"""
        token, plaintext = ApiToken.issue(self.user, name="bot")
        self.assertEqual(token.user, self.user)
        self.assertEqual(token.name, "bot")
        self.assertIsNotNone(plaintext)
        self.assertGreater(len(plaintext), 30)  # secrets.token_urlsafe(32) 約 43 字元

    def test_issue_stores_sha256_hash_not_plaintext(self):
        """DB 存的是 SHA-256 hex，不是明文"""
        token, plaintext = ApiToken.issue(self.user, name="bot")
        expected_hash = hashlib.sha256(plaintext.encode()).hexdigest()
        self.assertEqual(token.token_hash, expected_hash)
        self.assertNotEqual(token.token_hash, plaintext)

    def test_issue_unique_user_name_constraint(self):
        """同一 user 不能有同名 token"""
        ApiToken.issue(self.user, name="bot")
        with self.assertRaises(Exception):  # IntegrityError
            ApiToken.issue(self.user, name="bot")

    def test_different_users_can_share_name(self):
        """不同 user 可以用相同 name"""
        user2 = User.objects.create_user(username="bob", password="x")
        ApiToken.issue(self.user, name="bot")
        ApiToken.issue(user2, name="bot")  # 不應該 raise

    def test_one_user_multiple_named_tokens(self):
        """同一 user 可以有多把不同名 token"""
        ApiToken.issue(self.user, name="telegram-bot")
        ApiToken.issue(self.user, name="cli")
        self.assertEqual(self.user.api_tokens.count(), 2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test shortener.tests.ApiTokenModelTestCase -v 2`
Expected: ImportError / ModuleNotFoundError 或 AttributeError（`ApiToken` 不存在）。

- [ ] **Step 3: Add `ApiToken` model**

Append to `shortener/models.py`（在最後）：

```python
import hashlib
import secrets


class ApiToken(models.Model):
    """API 認證用的 token；每個 user 可有多把 named token，DB 只存 hash"""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="api_tokens",
        verbose_name="使用者",
    )
    token_hash = models.CharField(
        max_length=64, unique=True, db_index=True, verbose_name="Token Hash"
    )
    name = models.CharField(max_length=50, verbose_name="名稱")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="建立時間")
    last_used_at = models.DateTimeField(
        null=True, blank=True, verbose_name="最後使用時間"
    )

    class Meta:
        verbose_name = "API Token"
        verbose_name_plural = "API Tokens"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"], name="unique_user_token_name"
            ),
        ]

    def __str__(self):
        return f"{self.user.username} / {self.name}"

    @classmethod
    def issue(cls, user, name) -> tuple["ApiToken", str]:
        """建立 token，回傳 (token_obj, plaintext)。plaintext 只此一次有機會看到。"""
        plaintext = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(plaintext.encode()).hexdigest()
        token = cls.objects.create(user=user, token_hash=token_hash, name=name)
        return token, plaintext
```

- [ ] **Step 4: Generate migration**

Run: `python manage.py makemigrations shortener`
Expected: 產生 `shortener/migrations/0006_apitoken.py`。

- [ ] **Step 5: Apply migration**

Run: `python manage.py migrate`
Expected: `Applying shortener.0006_apitoken... OK`。

- [ ] **Step 6: Run tests to verify they pass**

Run: `python manage.py test shortener.tests.ApiTokenModelTestCase -v 2`
Expected: 5 tests pass。

- [ ] **Step 7: Stop for user to review and commit**

User commits `shortener/models.py`、`shortener/migrations/0006_apitoken.py`、`shortener/tests.py`。建議 commit message：`feat(shortener): add ApiToken model with hashed storage`。

---

## Task 2: Add `ApiTokenAdmin` with one-time plaintext display

**Files:**
- Modify: `shortener/admin.py`
- Modify: `shortener/tests.py`

- [ ] **Step 1: Write failing test for admin plaintext message**

Append to `shortener/tests.py`（接續 ApiToken 區塊）：

```python
from django.contrib.messages import get_messages
from django.contrib.admin.sites import AdminSite
from shortener.admin import ApiTokenAdmin


class ApiTokenAdminTestCase(TestCase):
    """ApiTokenAdmin save_model 應該顯示 plaintext 一次"""

    def setUp(self):
        self.user = User.objects.create_user(username="admin", password="x", is_staff=True, is_superuser=True)
        self.client.force_login(self.user)

    def test_admin_create_shows_plaintext_message(self):
        """從 admin 表單建立 ApiToken，應該回 messages 含 plaintext"""
        response = self.client.post(
            reverse("admin:shortener_apitoken_add"),
            data={"user": self.user.id, "name": "telegram-bot"},
            follow=True,
        )
        msgs = [str(m) for m in get_messages(response.wsgi_request)]
        # 至少一條 message 應該帶 token plaintext（用 prefix 檢查）
        self.assertTrue(
            any("API token issued" in m and "telegram-bot" in m for m in msgs),
            f"Expected plaintext message; got: {msgs}",
        )

    def test_admin_does_not_display_token_hash_field(self):
        """token_hash 不該出現在 add form 上"""
        response = self.client.get(reverse("admin:shortener_apitoken_add"))
        self.assertNotContains(response, "token_hash")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test shortener.tests.ApiTokenAdminTestCase -v 2`
Expected: NoReverseMatch 或 ImportError（admin 還沒註冊）。

- [ ] **Step 3: Register `ApiTokenAdmin` with custom save_model**

Modify `shortener/admin.py`：

```python
import hashlib
import secrets

from django.contrib import admin, messages

from .models import ApiToken, ClickLog, RateLimitEvent, URLModel

# (既有 URLModelAdmin / ClickLogAdmin / RateLimitEventAdmin 保持不動)


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    """ApiToken Admin：建立時自動產 plaintext + hash，並透過 messages 顯示 plaintext 一次"""

    list_display = ("user", "name", "created_at", "last_used_at")
    list_filter = ("created_at",)
    search_fields = ("user__username", "name")
    readonly_fields = ("created_at", "last_used_at")
    fields = ("user", "name", "created_at", "last_used_at")  # 不顯示 token_hash

    def save_model(self, request, obj, form, change):
        if not change:
            # 新建：產生 plaintext + 寫入 hash，由 super().save_model 正常存檔
            plaintext = secrets.token_urlsafe(32)
            obj.token_hash = hashlib.sha256(plaintext.encode()).hexdigest()
            super().save_model(request, obj, form, change)
            messages.success(
                request,
                f"API token issued for [{obj.user.username} / {obj.name}]: "
                f"{plaintext}  ⚠️ 此 token 只顯示這一次，請立即複製保存。",
            )
            return
        # 編輯既有 token：hash 不可變更，僅允許改 name（form 已經不顯示 token_hash）
        super().save_model(request, obj, form, change)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test shortener.tests.ApiTokenAdminTestCase -v 2`
Expected: 2 tests pass。

- [ ] **Step 5: Manual smoke check (optional)**

Run: `python manage.py runserver`，瀏覽器到 `/admin/shortener/apitoken/add/`，建立一筆，確認頁面頂端 success message 顯示 plaintext token。

- [ ] **Step 6: Stop for user to review and commit**

User commits `shortener/admin.py`、`shortener/tests.py`。建議 commit message：`feat(shortener): register ApiTokenAdmin with one-time plaintext display`。

---

## Task 3: Add `api_errors` helper module

**Files:**
- Create: `shortener/api_errors.py`
- Modify: `shortener/tests.py`

- [ ] **Step 1: Write failing tests for `api_error()` helper**

Append to `shortener/tests.py`：

```python
# ============================================================
# API Error Helper
# ============================================================
from shortener.api_errors import ErrorCode, api_error


class ApiErrorHelperTestCase(TestCase):
    """api_error helper 測試"""

    def test_returns_jsonresponse_with_error_envelope(self):
        resp = api_error(ErrorCode.URL_NOT_FOUND, "Short URL not found", status=404)
        self.assertEqual(resp.status_code, 404)
        body = resp.json()
        self.assertEqual(
            body, {"error": {"code": "URL_NOT_FOUND", "message": "Short URL not found"}}
        )

    def test_error_code_constants_uppercase(self):
        """確認 ErrorCode 全部 UPPER_SNAKE"""
        for name in dir(ErrorCode):
            if name.startswith("_"):
                continue
            self.assertTrue(name.isupper(), f"{name} should be UPPER_SNAKE")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test shortener.tests.ApiErrorHelperTestCase -v 2`
Expected: ImportError。

- [ ] **Step 3: Create `shortener/api_errors.py`**

```python
"""API 統一錯誤回應 helper"""

from django.http import JsonResponse


class ErrorCode:
    """API 錯誤代碼常數"""

    INVALID_REQUEST = "INVALID_REQUEST"
    UNAUTHORIZED = "UNAUTHORIZED"
    ACCESS_DENIED = "ACCESS_DENIED"
    USER_BANNED = "USER_BANNED"
    URL_NOT_FOUND = "URL_NOT_FOUND"
    URL_EXPIRED = "URL_EXPIRED"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    BLOCKED_DOMAIN = "BLOCKED_DOMAIN"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


def api_error(code: str, message: str, status: int) -> JsonResponse:
    """回傳統一格式的 JSON error envelope"""
    return JsonResponse(
        {"error": {"code": code, "message": message}},
        status=status,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test shortener.tests.ApiErrorHelperTestCase -v 2`
Expected: 2 tests pass。

- [ ] **Step 5: Stop for user to review and commit**

User commits `shortener/api_errors.py`、`shortener/tests.py`。建議 commit message：`feat(shortener): add api_error helper with unified envelope`。

---

## Task 4: Add `require_api_token` decorator

**Files:**
- Create: `shortener/api_auth.py`
- Modify: `shortener/tests.py`

- [ ] **Step 1: Write failing tests for `require_api_token`**

Append to `shortener/tests.py`：

```python
# ============================================================
# API Auth (require_api_token decorator)
# ============================================================
from django.http import HttpResponse, JsonResponse
from shortener.api_auth import require_api_token
from shortener.models import ApiToken


class RequireApiTokenTestCase(TestCase):
    """require_api_token decorator 測試"""

    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="api-user", password="x")
        _, self.plaintext = ApiToken.issue(self.user, name="bot")

    def _make_view(self):
        @require_api_token
        def view(request):
            return JsonResponse({"user_id": request.user.id})
        return view

    def test_valid_token_sets_request_user(self):
        view = self._make_view()
        req = self.factory.get("/api/v1/urls/", HTTP_AUTHORIZATION=f"Bearer {self.plaintext}")
        resp = view(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["user_id"], self.user.id)

    def test_missing_header_returns_401(self):
        view = self._make_view()
        req = self.factory.get("/api/v1/urls/")
        resp = view(req)
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"]["code"], "UNAUTHORIZED")

    def test_wrong_scheme_returns_401(self):
        view = self._make_view()
        req = self.factory.get("/api/v1/urls/", HTTP_AUTHORIZATION=f"Token {self.plaintext}")
        resp = view(req)
        self.assertEqual(resp.status_code, 401)

    def test_invalid_token_returns_401(self):
        view = self._make_view()
        req = self.factory.get("/api/v1/urls/", HTTP_AUTHORIZATION="Bearer not-a-valid-token")
        resp = view(req)
        self.assertEqual(resp.status_code, 401)

    def test_valid_token_updates_last_used_at(self):
        token = ApiToken.objects.get(user=self.user, name="bot")
        self.assertIsNone(token.last_used_at)
        view = self._make_view()
        req = self.factory.get("/api/v1/urls/", HTTP_AUTHORIZATION=f"Bearer {self.plaintext}")
        view(req)
        token.refresh_from_db()
        self.assertIsNotNone(token.last_used_at)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test shortener.tests.RequireApiTokenTestCase -v 2`
Expected: ImportError。

- [ ] **Step 3: Create `shortener/api_auth.py`**

```python
"""API token 認證 decorator"""

import hashlib
from functools import wraps

from django.utils import timezone

from .api_errors import ErrorCode, api_error
from .models import ApiToken


def require_api_token(view_func):
    """
    驗證 Authorization: Bearer <token> header。
    成功則設定 request.user = token.user 並更新 token.last_used_at。
    失敗一律回 401 JSON error。
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header.startswith("Bearer "):
            return api_error(ErrorCode.UNAUTHORIZED, "Missing or invalid Authorization header", 401)

        plaintext = header[len("Bearer "):].strip()
        if not plaintext:
            return api_error(ErrorCode.UNAUTHORIZED, "Empty token", 401)

        token_hash = hashlib.sha256(plaintext.encode()).hexdigest()
        try:
            token = ApiToken.objects.select_related("user").get(token_hash=token_hash)
        except ApiToken.DoesNotExist:
            return api_error(ErrorCode.UNAUTHORIZED, "Invalid token", 401)

        request.user = token.user
        # 順手更新 last_used_at（不阻塞 view 執行）
        ApiToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
        return view_func(request, *args, **kwargs)

    return wrapper
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test shortener.tests.RequireApiTokenTestCase -v 2`
Expected: 5 tests pass。

- [ ] **Step 5: Stop for user to review and commit**

User commits `shortener/api_auth.py`、`shortener/tests.py`。建議 commit message：`feat(shortener): add require_api_token decorator with hash lookup`。

---

## Task 5: Add `api_serializers`

**Files:**
- Create: `shortener/api_serializers.py`
- Modify: `shortener/tests.py`

- [ ] **Step 1: Write failing tests for serializers**

Append to `shortener/tests.py`：

```python
# ============================================================
# API Serializers
# ============================================================
from shortener.api_serializers import serialize_url, serialize_url_list


class ApiSerializersTestCase(TestCase):
    """serialize_url / serialize_url_list 測試"""

    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="alice", password="x")
        self.url = URLService.create_short_url(self.user, "https://example.com/")

    def test_serialize_url_basic_fields(self):
        req = self.factory.get("/")
        d = serialize_url(self.url, req)
        self.assertEqual(d["short_code"], self.url.short_code)
        self.assertEqual(d["original_url"], "https://example.com/")
        self.assertTrue(d["short_url"].endswith(f"/{self.url.short_code}/"))
        self.assertTrue(d["is_active"])
        self.assertIsNone(d["expires_at"])  # 無到期時間
        self.assertIsNone(d.get("click_count"))  # 沒 annotate 應該是 None

    def test_serialize_url_with_click_count_annotation(self):
        annotated = URLService.get_user_urls_with_stats(self.user).first()
        req = self.factory.get("/")
        d = serialize_url(annotated, req)
        self.assertEqual(d["click_count"], 0)

    def test_serialize_url_list_pagination_shape(self):
        # 多建幾筆來看分頁
        for i in range(3):
            URLService.create_short_url(self.user, f"https://example.com/{i}")
        qs = URLService.get_user_urls_with_stats(self.user)
        req = self.factory.get("/")
        d = serialize_url_list(qs, page=1, page_size=2, request=req)
        self.assertEqual(len(d["data"]), 2)
        self.assertEqual(d["pagination"], {"page": 1, "page_size": 2, "total": 4})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test shortener.tests.ApiSerializersTestCase -v 2`
Expected: ImportError。

- [ ] **Step 3: Create `shortener/api_serializers.py`**

```python
"""URLModel → API response dict 轉換 helper（DRF migration 友善）"""

from django.core.paginator import Paginator
from django.db.models import QuerySet
from django.http import HttpRequest

from .models import URLModel


def serialize_url(url_obj: URLModel, request: HttpRequest) -> dict:
    """單筆 URLModel → API response dict"""
    return {
        "short_code": url_obj.short_code,
        "short_url": request.build_absolute_uri(f"/{url_obj.short_code}/"),
        "original_url": url_obj.original_url,
        "is_active": url_obj.is_active,
        "click_count": getattr(url_obj, "click_count", None),
        "created_at": url_obj.created_at.isoformat(),
        "expires_at": url_obj.expires_at.isoformat() if url_obj.expires_at else None,
    }


def serialize_url_list(
    queryset: QuerySet,
    page: int,
    page_size: int,
    request: HttpRequest,
) -> dict:
    """paginated 列表 → API response dict"""
    paginator = Paginator(queryset, page_size)
    page_obj = paginator.get_page(page)
    return {
        "data": [serialize_url(u, request) for u in page_obj.object_list],
        "pagination": {
            "page": page_obj.number,
            "page_size": page_size,
            "total": paginator.count,
        },
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python manage.py test shortener.tests.ApiSerializersTestCase -v 2`
Expected: 3 tests pass。

- [ ] **Step 5: Stop for user to review and commit**

User commits `shortener/api_serializers.py`、`shortener/tests.py`。建議 commit message：`feat(shortener): add api_serializers helpers`。

---

## Task 6: Add `api_shorten` view + wire URL routing

**Files:**
- Create: `shortener/api_views.py`
- Create: `shortener/api_urls.py`
- Modify: `core/urls.py`
- Modify: `shortener/tests.py`

> Routing 跟 view 一起做，因為測試需要透過 URL 打 view。

- [ ] **Step 1: Write failing tests for `POST /api/v1/shorten/`**

Append to `shortener/tests.py`：

```python
# ============================================================
# API Views: POST /api/v1/shorten/
# ============================================================
import json
from shortener.models import ApiToken


class ApiShortenTestCase(TestCase):
    """POST /api/v1/shorten/ 測試"""

    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="x")
        _, self.plaintext = ApiToken.issue(self.user, name="bot")
        self.auth = f"Bearer {self.plaintext}"

    def _post(self, body, auth=None):
        return self.client.post(
            "/api/v1/shorten/",
            data=json.dumps(body),
            content_type="application/json",
            HTTP_AUTHORIZATION=auth or self.auth,
        )

    def test_create_new_returns_201(self):
        resp = self._post({"original_url": "https://example.com/a"})
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertTrue(body["created"])
        self.assertEqual(body["original_url"], "https://example.com/a")
        self.assertTrue(body["short_url"].endswith(f"/{body['short_code']}/"))

    def test_existing_returns_200(self):
        self._post({"original_url": "https://example.com/dup"})
        resp = self._post({"original_url": "https://example.com/dup"})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["created"])

    def test_invalid_url_returns_422_validation(self):
        resp = self._post({"original_url": "not-a-url"})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["error"]["code"], "VALIDATION_ERROR")

    def test_missing_field_returns_400(self):
        resp = self._post({})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "INVALID_REQUEST")

    def test_unauthorized_returns_401(self):
        resp = self.client.post(
            "/api/v1/shorten/",
            data=json.dumps({"original_url": "https://x.com"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)

    def test_blocked_domain_returns_422(self):
        # blocklist.txt 內預期有條目；用一個一定在 blocklist 的域名
        # 若你的 blocklist.txt 內沒固定條目，這個 test 可改用 mock。
        from shortener.services import BlocklistService
        # 找出 blocklist 第一個條目來測
        blocked = next(iter(BlocklistService._load()), None)
        if not blocked:
            self.skipTest("blocklist.txt 為空，無法測 BLOCKED_DOMAIN")
        resp = self._post({"original_url": f"https://{blocked}/x"})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["error"]["code"], "BLOCKED_DOMAIN")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test shortener.tests.ApiShortenTestCase -v 2`
Expected: 404 (URL 沒掛) 或 ImportError。

- [ ] **Step 3: Create `shortener/api_views.py` with `api_shorten`**

```python
"""API Views: token-authenticated JSON endpoints"""

import json

from django.core.exceptions import ValidationError
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django_ratelimit.decorators import ratelimit

from .api_auth import require_api_token
from .api_errors import ErrorCode, api_error
from .api_serializers import serialize_url
from .exceptions import (
    BlockedDomainError,
    QuotaExceededError,
    UserBannedError,
)
from .services import RateLimitService, URLService


@csrf_exempt
@require_http_methods(["POST"])
@require_api_token              # 必須外層（先設定 request.user）
@ratelimit(key="user", rate="5/m", block=False)  # 內層
def api_shorten(request: HttpRequest) -> JsonResponse:
    """POST /api/v1/shorten/ — 縮網址"""
    if getattr(request, "limited", False):
        RateLimitService.register_hit(request.user, request)
        return api_error(ErrorCode.RATE_LIMITED, "Too many requests", 429)

    try:
        payload = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return api_error(ErrorCode.INVALID_REQUEST, "Body must be valid JSON", 400)

    original_url = payload.get("original_url")
    if not isinstance(original_url, str) or not original_url.strip():
        return api_error(ErrorCode.INVALID_REQUEST, "Missing or invalid 'original_url'", 400)

    try:
        url_obj, created = URLService.get_or_create_short_url(request.user, original_url.strip())
    except ValidationError as e:
        return api_error(ErrorCode.VALIDATION_ERROR, str(e), 422)
    except BlockedDomainError:
        return api_error(ErrorCode.BLOCKED_DOMAIN, "此網域不允許縮短", 422)
    except QuotaExceededError as e:
        return api_error(ErrorCode.QUOTA_EXCEEDED, str(e), 422)
    except UserBannedError:
        return api_error(ErrorCode.USER_BANNED, "User is banned", 403)

    body = {**serialize_url(url_obj, request), "created": created}
    status = 201 if created else 200
    return JsonResponse(body, status=status)
```

- [ ] **Step 4: Create `shortener/api_urls.py`**

```python
"""API URL 路由（prefix: /api/v1/）"""

from django.urls import path

from . import api_views

urlpatterns = [
    path("shorten/", api_views.api_shorten, name="api_shorten"),
    # api_list_urls / api_stats 在後續 task 加入
]
```

- [ ] **Step 5: Wire `/api/v1/` into `core/urls.py`**

Modify `core/urls.py`：

```python
urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("users.urls")),
    path("accounts/", include("allauth.urls")),
    path("api/v1/", include("shortener.api_urls")),  # ← 新增；必須在 catch-all 之前
    path("", include("shortener.urls")),
]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python manage.py test shortener.tests.ApiShortenTestCase -v 2`
Expected: 6 tests pass（`test_blocked_domain_returns_422` 若 blocklist 為空會 skip）。

- [ ] **Step 7: Manual smoke check**

啟動 server: `python manage.py runserver`
另一個 terminal:
```bash
TOKEN="<你 admin 產的 plaintext>"
curl -i -X POST http://127.0.0.1:8000/api/v1/shorten/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"original_url":"https://example.com/test"}'
```
Expected: `HTTP/1.1 201 Created` + JSON body。

- [ ] **Step 8: Stop for user to review and commit**

User commits `shortener/api_views.py`、`shortener/api_urls.py`、`core/urls.py`、`shortener/tests.py`。建議 commit message：`feat(shortener): add POST /api/v1/shorten/ endpoint`。

---

## Task 7: Add `api_list_urls` view

**Files:**
- Modify: `shortener/api_views.py`
- Modify: `shortener/api_urls.py`
- Modify: `shortener/tests.py`

- [ ] **Step 1: Write failing tests for `GET /api/v1/urls/`**

Append to `shortener/tests.py`：

```python
# ============================================================
# API Views: GET /api/v1/urls/
# ============================================================


class ApiListUrlsTestCase(TestCase):
    """GET /api/v1/urls/ 測試"""

    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="x")
        _, self.plaintext = ApiToken.issue(self.user, name="bot")
        self.auth = f"Bearer {self.plaintext}"
        # 建 3 筆給 alice
        for i in range(3):
            URLService.create_short_url(self.user, f"https://example.com/a{i}")
        # 另一個 user 建 1 筆，不該出現在 alice 的 list
        bob = User.objects.create_user(username="bob", password="x")
        URLService.create_short_url(bob, "https://example.com/bob")

    def _get(self, qs=""):
        return self.client.get(f"/api/v1/urls/{qs}", HTTP_AUTHORIZATION=self.auth)

    def test_returns_only_owners_urls(self):
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["pagination"]["total"], 3)
        for item in body["data"]:
            self.assertIn("short_code", item)
            self.assertIn("click_count", item)

    def test_pagination_works(self):
        resp = self._get("?page=1&page_size=2")
        body = resp.json()
        self.assertEqual(len(body["data"]), 2)
        self.assertEqual(body["pagination"], {"page": 1, "page_size": 2, "total": 3})

    def test_invalid_pagination_falls_back_to_defaults(self):
        resp = self._get("?page=abc&page_size=xyz")
        # 不該 500，應該回正常結果
        self.assertEqual(resp.status_code, 200)

    def test_page_size_capped_at_100(self):
        resp = self._get("?page_size=9999")
        body = resp.json()
        self.assertEqual(body["pagination"]["page_size"], 100)

    def test_unauthorized_returns_401(self):
        resp = self.client.get("/api/v1/urls/")
        self.assertEqual(resp.status_code, 401)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test shortener.tests.ApiListUrlsTestCase -v 2`
Expected: 404（路徑沒掛）。

- [ ] **Step 3: Add `api_list_urls` to `shortener/api_views.py`**

Append to `shortener/api_views.py`：

```python
from .api_serializers import serialize_url_list


PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 100


def _parse_int(value, default, cap=None):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    if cap is not None and n > cap:
        return cap
    return max(n, 1)


@require_http_methods(["GET"])
@require_api_token
def api_list_urls(request: HttpRequest) -> JsonResponse:
    """GET /api/v1/urls/ — 列出該 user 的 URL（含點擊數）"""
    page = _parse_int(request.GET.get("page"), default=1)
    page_size = _parse_int(
        request.GET.get("page_size"), default=PAGE_SIZE_DEFAULT, cap=PAGE_SIZE_MAX
    )
    qs = URLService.get_user_urls_with_stats(request.user)
    return JsonResponse(serialize_url_list(qs, page, page_size, request))
```

- [ ] **Step 4: Wire route in `shortener/api_urls.py`**

```python
urlpatterns = [
    path("shorten/", api_views.api_shorten, name="api_shorten"),
    path("urls/", api_views.api_list_urls, name="api_list_urls"),
]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python manage.py test shortener.tests.ApiListUrlsTestCase -v 2`
Expected: 5 tests pass。

- [ ] **Step 6: Stop for user to review and commit**

User commits `shortener/api_views.py`、`shortener/api_urls.py`、`shortener/tests.py`。建議 commit message：`feat(shortener): add GET /api/v1/urls/ endpoint`。

---

## Task 8: Add `api_stats` view

**Files:**
- Modify: `shortener/api_views.py`
- Modify: `shortener/api_urls.py`
- Modify: `shortener/tests.py`

- [ ] **Step 1: Write failing tests for `GET /api/v1/stats/<code>/`**

Append to `shortener/tests.py`：

```python
# ============================================================
# API Views: GET /api/v1/stats/<code>/
# ============================================================
from datetime import timedelta


class ApiStatsTestCase(TestCase):
    """GET /api/v1/stats/<code>/ 測試"""

    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="x")
        _, self.plaintext = ApiToken.issue(self.user, name="bot")
        self.auth = f"Bearer {self.plaintext}"
        self.url = URLService.create_short_url(self.user, "https://example.com/a")

    def _get(self, code, auth=None):
        return self.client.get(
            f"/api/v1/stats/{code}/", HTTP_AUTHORIZATION=auth or self.auth
        )

    def test_owner_returns_200_with_stats(self):
        resp = self._get(self.url.short_code)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["short_code"], self.url.short_code)
        self.assertEqual(body["total_clicks"], 0)

    def test_unknown_code_returns_404(self):
        resp = self._get("zzzzzz")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["error"]["code"], "URL_NOT_FOUND")

    def test_other_users_url_returns_403(self):
        bob = User.objects.create_user(username="bob", password="x")
        bob_url = URLService.create_short_url(bob, "https://example.com/bob")
        resp = self._get(bob_url.short_code)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], "ACCESS_DENIED")

    def test_expired_url_returns_410(self):
        self.url.expires_at = timezone.now() - timedelta(days=1)
        self.url.save()
        resp = self._get(self.url.short_code)
        self.assertEqual(resp.status_code, 410)
        self.assertEqual(resp.json()["error"]["code"], "URL_EXPIRED")

    def test_unauthorized_returns_401(self):
        resp = self.client.get(f"/api/v1/stats/{self.url.short_code}/")
        self.assertEqual(resp.status_code, 401)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test shortener.tests.ApiStatsTestCase -v 2`
Expected: 404 (路徑沒掛)。

- [ ] **Step 3: Add `api_stats` to `shortener/api_views.py`**

Append imports:

```python
from .exceptions import AccessDeniedError, UrlExpiredError, UrlNotFoundError
from .services import AnalyticsService
```

Append view:

```python
@require_http_methods(["GET"])
@require_api_token
def api_stats(request: HttpRequest, code: str) -> JsonResponse:
    """GET /api/v1/stats/<code>/ — 單一 URL 統計（不含 click logs 列表）"""
    try:
        url_obj = URLService.get_url_by_code(code, check_active=False)
        URLService.verify_owner(url_obj, request.user)
    except UrlNotFoundError:
        return api_error(ErrorCode.URL_NOT_FOUND, "Short URL not found", 404)
    except UrlExpiredError:
        return api_error(ErrorCode.URL_EXPIRED, "URL has expired", 410)
    except AccessDeniedError:
        return api_error(ErrorCode.ACCESS_DENIED, "You do not own this URL", 403)

    stats = AnalyticsService.get_url_stats(url_obj)
    return JsonResponse({
        "short_code": url_obj.short_code,
        "original_url": url_obj.original_url,
        "is_active": url_obj.is_active,
        "total_clicks": stats["total_clicks"],
        "created_at": url_obj.created_at.isoformat(),
        "expires_at": url_obj.expires_at.isoformat() if url_obj.expires_at else None,
    })
```

- [ ] **Step 4: Wire route in `shortener/api_urls.py`**

```python
urlpatterns = [
    path("shorten/", api_views.api_shorten, name="api_shorten"),
    path("urls/", api_views.api_list_urls, name="api_list_urls"),
    path("stats/<str:code>/", api_views.api_stats, name="api_stats"),
]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python manage.py test shortener.tests.ApiStatsTestCase -v 2`
Expected: 5 tests pass。

- [ ] **Step 6: Stop for user to review and commit**

User commits `shortener/api_views.py`、`shortener/api_urls.py`、`shortener/tests.py`。建議 commit message：`feat(shortener): add GET /api/v1/stats/<code>/ endpoint`。

---

## Task 9: Full-suite regression check

**Files:** none modified

- [ ] **Step 1: Run the entire shortener test suite**

Run: `python manage.py test shortener -v 2`
Expected: 全部 pass，無 regression。

- [ ] **Step 2: Run the entire project test suite**

Run: `python manage.py test -v 2`
Expected: 全部 pass，包括 users app。

- [ ] **Step 3: Black + isort 格式化**

Run: `black . && isort .`
Expected: no diff（如有，user 可選擇 commit 格式化變更）。

- [ ] **Step 4: Stop for user to verify all green**

User 確認所有測試 pass、格式無誤後，這個 plan 完成。

---

## Task 10: Manual end-to-end smoke (optional but recommended)

**Files:** none modified

> 這個 task 不寫程式，只跑 curl 確認串接 OK。Bot 程式碼之後另開 spec。

- [ ] **Step 1: Boot dev server**

Run: `python manage.py runserver`

- [ ] **Step 2: 從 admin 建 token**

瀏覽器開 `/admin/shortener/apitoken/add/`，填 user + name，submit，**複製 success message 顯示的 plaintext**。

- [ ] **Step 3: 測 POST /api/v1/shorten/**

```bash
TOKEN="<plaintext>"
curl -s -X POST http://127.0.0.1:8000/api/v1/shorten/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"original_url":"https://example.com/hello"}' | jq
```
Expected: `{"short_code":"...","short_url":"...","created":true,...}`。

- [ ] **Step 4: 測 GET /api/v1/urls/**

```bash
curl -s "http://127.0.0.1:8000/api/v1/urls/?page=1&page_size=10" \
  -H "Authorization: Bearer $TOKEN" | jq
```
Expected: `{"data":[...], "pagination":{...}}`。

- [ ] **Step 5: 測 GET /api/v1/stats/<code>/**

```bash
CODE="<step 3 回傳的 short_code>"
curl -s "http://127.0.0.1:8000/api/v1/stats/$CODE/" \
  -H "Authorization: Bearer $TOKEN" | jq
```
Expected: `{"short_code":"...","total_clicks":0,...}`。

- [ ] **Step 6: 測 401 路徑**

```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  http://127.0.0.1:8000/api/v1/urls/
```
Expected: `401`。

- [ ] **Step 7: 測 rate limit**

連打 6 次：
```bash
for i in 1 2 3 4 5 6; do
  curl -s -o /dev/null -w "$i: %{http_code}\n" \
    -X POST http://127.0.0.1:8000/api/v1/shorten/ \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"original_url\":\"https://example.com/rl$i\"}"
done
```
Expected: 前 5 次 200/201，第 6 次 `429`。

- [ ] **Step 8: Done**

API 串接完成。下一步另開 `tg-bot-design.md` spec 做 Telegram bot 程式碼。

---

## Verification Summary

| 項目 | 驗證方式 |
|---|---|
| Model + migration | Task 1 unit tests + `python manage.py migrate` 成功 |
| Admin plaintext UX | Task 2 unit tests + Task 10 step 2 手動 |
| Auth decorator | Task 4 unit tests（5 個情境） |
| Serializers | Task 5 unit tests |
| 3 個 endpoint | Task 6/7/8 unit tests + Task 10 curl smoke |
| URL routing 不衝突 | Task 6 + Task 9 全測試 pass |
| Rate limit 共用 web 桶子 | Task 10 step 7 |
| Decorator 順序正確 | Task 6 step 3 已照 spec §8 順序寫死 |
| 格式 | Task 9 step 3 black + isort |

**Critical files reused（spec 對應）：**
- `URLService.get_or_create_short_url` (`shortener/services.py:113`) — Task 6
- `URLService.get_user_urls_with_stats` (`shortener/services.py:232`) — Task 7
- `URLService.get_url_by_code` + `verify_owner` (`shortener/services.py:179, 317`) — Task 8
- `AnalyticsService.get_url_stats` (`shortener/services.py:372`) — Task 8
- `RateLimitService.register_hit` (`shortener/services.py:476`) — Task 6
- `BlocklistService` (`shortener/services.py:40`) — Task 6 test
- Domain exceptions (`shortener/exceptions.py`) — Task 6/8

**Out of scope (per spec §13)：**
- DRF migration、bot 程式碼、bot 部署 systemd unit、token 過期、API 文件自動產生、webhook 模式、click logs 列表 API。
