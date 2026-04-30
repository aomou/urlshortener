# API Endpoint + Telegram Bot 對接架構 Spec

**Date:** 2026-04-30
**Status:** Draft
**Scope:** API endpoint 設計、Token 機制、Telegram Bot 部署架構決策（**不含 bot 程式碼實作**）

---

## 1. Goals

1. 為 Django URL shortener 新增 JSON API endpoint，讓外部 client（首位消費者：Telegram bot 自用）可以呼叫
2. 設計一套 token-based 認證機制，跟現有 session-based web view 並存
3. 確立 Telegram bot 的部署架構（polling vs webhook），避免之後實作時才反推 API 設計
4. **API 設計需 DRF 友善**——未來能以最小工作量換成 Django REST Framework

## 2. Non-goals

- 不開放給其他登入使用者（單一自用，admin 手動產 token）
- 不寫 bot 業務邏輯 / command handler（另開 `tg-bot-design.md`）
- 不寫部署細節（systemd unit 內容、docker-compose service 設定）
- 不引入 DRF（這份 spec 是「為了未來能換 DRF」做準備，本身不裝 DRF）
- 不引入 pydantic（input 驗證採輕量手寫）
- 不做 GraphQL、webhook、SSE 等其他通訊模式

---

## 3. Architecture Overview

```
┌───────────────────────────┐
│  Telegram (api.telegram)  │
└────────────┬──────────────┘
             │ long polling
             ↓
┌───────────────────────────┐         ┌──────────────────────┐
│  bot process (long-run)   │ ──────→ │  Django (gunicorn)   │
│  - python-telegram-bot    │  HTTP   │  - 既有 web view     │
│  - 從 .env 讀 API token   │  Bearer │  - 新增 /api/v1/*    │
│                           │  token  │  - service 層共用    │
└───────────────────────────┘         └──────────┬───────────┘
                                                 │
                                                 ↓
                                          ┌─────────────┐
                                          │ PostgreSQL  │
                                          └─────────────┘
```

**設計原則：**

- Bot 與 Django 同 repo、獨立 process（部署彈性）
- Bot 不直接讀 ORM，**純 HTTP client** → 強迫 API 設計合理
- Service 層（`URLService`、`AnalyticsService`）100% 重用，零修改
- Web view（session auth）跟 API view（token auth）並存，互不影響
- Bot ↔ Django 走 localhost（同 VPS），無對外網路成本

**Polling 而非 webhook 的理由：**

- 「新增 API endpoint」這個需求需要真實消費者驗證——webhook 模式下 bot 直接讀 ORM、API 變成「為了未來而做」
- 開發體驗：本機 `python bot.py` 配 BotFather token 就能測；webhook 需要 ngrok 或部署到 VPS
- Long polling 不是「每秒打你 server」——bot 是去打 `api.telegram.org` 的長連接（約 50 秒回一次），Django 只在使用者真的傳訊息時被命中
- 自用情境流量極低（一天 < 50 次 API call），bot process idle 約 30-50MB RAM、~0% CPU

---

## 4. Data Model

新增 model `ApiToken`，每個 user 可以有多把 named token：

```python
# shortener/models.py
import hashlib
import secrets

class ApiToken(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="api_tokens"
    )
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    name = models.CharField(max_length=50)  # 必填，例如 "telegram-bot"、"cli"
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"], name="unique_user_token_name"
            ),
        ]

    @classmethod
    def issue(cls, user, name) -> tuple["ApiToken", str]:
        """建立 token，回傳 (token_obj, plaintext)。plaintext 只此一次有機會看到。"""
        plaintext = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(plaintext.encode()).hexdigest()
        token = cls.objects.create(user=user, token_hash=token_hash, name=name)
        return token, plaintext
```

**設計重點：**

- **多 token per user**：bot / CLI / 未來 webhook receiver 各自一把，共用 user 的 quota 與 URL list，但隔離 revoke
- **`(user, name)` unique**：避免同一個 user 重複建相同 name 的 token
- **Hash 儲存**：DB 只存 SHA-256 hash；明文只在建立當下回傳一次。DB dump 外洩也無法回推 token
- Token 明文用 `secrets.token_urlsafe(32)`（~43 字元、256 bit entropy → 不需要 salt 或 bcrypt）
- 認證時對 incoming token 算 SHA-256 → `ApiToken.objects.get(token_hash=...)`
- 不加 expiry：admin 管理，過期反而麻煩
- `last_used_at`：每次 API 命中時更新，admin 可判斷 token 是否還活著

**Migration：** 純加新表 `shortener_apitoken`，不動既有 model，零 downtime。`deploy.sh` 已含 `migrate`，無需新增部署步驟。

**Admin：**
- `ApiTokenAdmin` 註冊到 Django admin
- `list_display`: `user`, `name`, `created_at`, `last_used_at`
- **不顯示 `token_hash`**（沒意義，看不到原文）
- 建立時透過 admin custom action 或覆寫 `save_model`：呼叫 `ApiToken.issue()`，**用 Django messages 把 plaintext 顯示給 admin 一次**（離開頁面後永遠看不到）
- Regenerate：刪掉舊 token、建新的（hash 不可逆，沒辦法「就地換掉」）

---

## 5. API Endpoints

全部 JSON、prefix `/api/v1/`。

**所有 endpoint 一律帶尾斜線**——既有 web 端點都是這個慣例；Django `APPEND_SLASH=True` 預設下，沒尾斜線的 POST 會 301 redirect 並 strip body，API 直接壞掉。

### 5.1 `POST /api/v1/shorten/`

縮網址。

**Request:**
```json
{ "original_url": "https://example.com/very/long/path" }
```

**Response（status 依 `created` 旗標分流）：**

| 情境 | Status | 語意 |
|---|---|---|
| 新建立 | `201 Created` | 真的產生新資源 |
| 已存在（同 user 已縮過同一 URL）| `200 OK` | 沒產生新資源、回傳既有那筆 |

```json
{
  "short_code": "abc123",
  "short_url": "https://你的網域/abc123/",
  "original_url": "https://example.com/very/long/path",
  "created": true,
  "expires_at": "2026-05-30T12:00:00Z"
}
```

Bot client 用 status code 或 `created` 旗標任一個判斷皆可；推薦用 status code（在 HTTP 層直接分流訊息）。

### 5.2 `GET /api/v1/urls/`

列出自己的 URL（含點擊數）。

**Query params:** `?page=1&page_size=20`（預設 20、最大 100）

**Response 200:**
```json
{
  "data": [
    {
      "short_code": "abc123",
      "short_url": "https://你的網域/abc123/",
      "original_url": "...",
      "click_count": 42,
      "is_active": true,
      "created_at": "...",
      "expires_at": "..."
    }
  ],
  "pagination": { "page": 1, "page_size": 20, "total": 35 }
}
```

### 5.3 `GET /api/v1/stats/<code>/`

單一 URL 統計（**不含**點擊 logs 列表，避免 response 大小不可控；要看 logs 走 web 介面）。

**Response 200:**
```json
{
  "short_code": "abc123",
  "original_url": "...",
  "total_clicks": 42,
  "is_active": true,
  "created_at": "...",
  "expires_at": "..."
}
```

**設計重點：**

- 命名 `snake_case`（與既有 model + DRF 預設一致）
- `short_url` 由 server 組好給 client，bot 不需自己拼網域
- 三個 endpoint 都是 thin wrapper，service 層全現成（`get_or_create_short_url` / `get_user_urls_with_stats` / `get_url_stats`）

---

## 6. Authentication

`Authorization: Bearer <token>` header。

**新增 decorator：**

```python
# shortener/api_auth.py
import hashlib

def require_api_token(view_func):
    """
    1. 解析 Authorization: Bearer <token> header
    2. 對 incoming token 算 SHA-256 → ApiToken.objects.get(token_hash=...)
    3. 設 request.user = token.user
    4. 順手更新 token.last_used_at
    5. 任何失敗 → 回 401 JSON error
    """
```

未來換 DRF：寫一個 `BearerTokenAuthentication(TokenAuthentication)` subclass 把 `keyword = "Bearer"`，在 view 套上 `permission_classes = [BearerTokenAuthentication]`。**bot 端 header 格式維持 `Bearer <token>` 不變**。注意 DRF 內建的 `Token` model 預設明文存儲，migration 時要保留我們現在的 hash 機制（覆寫 `authenticate_credentials`）。

CSRF：API view 全部 `@csrf_exempt`（token auth 不需要 CSRF token）。

---

## 7. Error Handling

**統一錯誤格式：**

```json
{
  "error": {
    "code": "QUOTA_EXCEEDED",
    "message": "已達配額上限 (10 個)"
  }
}
```

**Status code 對應：**

| HTTP | code | 觸發場景 |
|------|------|---------|
| 400 | `INVALID_REQUEST` | JSON 格式錯 / 缺欄位 |
| 401 | `UNAUTHORIZED` | 沒帶 token / token 無效 |
| 403 | `ACCESS_DENIED` | 試圖看別人的 URL stats（`AccessDeniedError`） |
| 403 | `USER_BANNED` | `UserBannedError` |
| 404 | `URL_NOT_FOUND` | `UrlNotFoundError` |
| 410 | `URL_EXPIRED` | `UrlExpiredError` |
| 422 | `VALIDATION_ERROR` | URL 格式錯（service 的 `ValidationError`） |
| 422 | `BLOCKED_DOMAIN` | `BlockedDomainError` |
| 422 | `QUOTA_EXCEEDED` | `QuotaExceededError` |
| 429 | `RATE_LIMITED` | 觸發 rate limit |
| 500 | `INTERNAL_ERROR` | 其他 exception，**不洩露 traceback** |

**實作：** 寫一個 `api_error(code, message, status)` helper，view 內 try/except service 層的 domain exceptions 後轉換。

---

## 8. Rate Limiting

**策略：跟 web view 共用同一桶子。**

```python
@require_api_token              # 必須外層（先執行）
@ratelimit(key="user", rate="5/m", block=False)  # 內層（後執行）
def api_shorten(request):
    if getattr(request, "limited", False):
        RateLimitService.register_hit(request.user, request)
        return api_error("RATE_LIMITED", "Too many requests", status=429)
    ...
```

**Decorator 順序強制要求：** `@require_api_token` **必須在外層**、`@ratelimit` 在內層。理由：`django-ratelimit` 在請求進入時就讀 `request.user` 算 cache key；若 `@require_api_token` 在內層，`request.user` 還是 `AnonymousUser`，所有未授權請求共用同一 bucket、授權使用者沒有 per-user limit → rate limit 失效。

**重點：**

- 只對寫入 endpoint（`POST /shorten/`）加 rate limit；讀取 endpoint 不加
- `key="user"`：web 跟 API 共用配額（防止繞道濫用）
- 觸發後一樣呼叫 `RateLimitService.register_hit()`，10 分鐘 5 次照樣會 ban
- Bot 端要實作 429 退讓邏輯（bot impl spec 處理）

---

## 9. Serialization Strategy（DRF migration 友善）

新增 `shortener/api_serializers.py`：

```python
def serialize_url(url_obj, request) -> dict:
    """URLModel → API response dict"""
    return {
        "short_code": url_obj.short_code,
        "short_url": request.build_absolute_uri(f"/{url_obj.short_code}/"),
        "original_url": url_obj.original_url,
        "is_active": url_obj.is_active,
        "click_count": getattr(url_obj, "click_count", None),
        "created_at": url_obj.created_at.isoformat(),
        "expires_at": url_obj.expires_at.isoformat() if url_obj.expires_at else None,
    }

def serialize_url_list(queryset, page, page_size, request) -> dict:
    """paginated 列表 → API response dict"""
    ...
```

**未來 DRF migration 對照：**

| | 現在（plain function） | 未來 DRF |
|---|---|---|
| File 名 | `api_serializers.py` | 同名 |
| 函式 `serialize_url` | dict 轉換 | 改成 `URLSerializer(ModelSerializer)` class |
| Input 驗證 | view 內手寫 + `URLValidator` | 改成 `serializer.is_valid()` |

**Input 驗證：** view 內手動檢查 JSON 形狀（`original_url` 是否存在 + 是字串），URL 格式驗證沿用 service 層既有的 `URLValidator`（會 raise `ValidationError`，view catch）。**不用 Django Form**——Form 與 DRF Serializer API 不相容，會白寫。

---

## 10. URL Routing 與檔案配置

**修改 `core/urls.py`：**

```python
urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("users.urls")),
    path("accounts/", include("allauth.urls")),
    path("api/v1/", include("shortener.api_urls")),  # 新增
    path("", include("shortener.urls")),             # 內含 catch-all <code>/
]
```

**新增 `shortener/api_urls.py`：**

```python
urlpatterns = [
    path("shorten/", api_views.api_shorten, name="api_shorten"),
    path("urls/", api_views.api_list_urls, name="api_list_urls"),
    path("stats/<str:code>/", api_views.api_stats, name="api_stats"),
]
```

**檔案清單：**

| 動作 | 檔案 | 用途 |
|---|---|---|
| 新增 | `shortener/api_urls.py` | API URL 路由 |
| 新增 | `shortener/api_views.py` | API view functions |
| 新增 | `shortener/api_auth.py` | `require_api_token` decorator |
| 新增 | `shortener/api_serializers.py` | dict 轉換 helper |
| 新增 | `shortener/api_errors.py` | `api_error()` helper + error code constants |
| 新增 | `shortener/migrations/000X_apitoken.py` | 自動產生 |
| 修改 | `core/urls.py` | 加 `/api/v1/` 路由 |
| 修改 | `shortener/admin.py` | 註冊 `ApiTokenAdmin` |
| 修改 | `shortener/models.py` | 加 `ApiToken` model |

**關鍵：** `/api/v1/` 必須放在 `path("", include("shortener.urls"))` **之前**，否則 `api` 會被 catch-all `<code>/` 吃掉。

---

## 11. Telegram Bot 設定步驟

**範圍：寫到「架構 + 設定流程」，bot 程式碼另開 spec。**

### 11.1 一次性設定流程

**步驟 1：在 Telegram 建立 bot**
- 找 BotFather (`@BotFather`) → `/newbot` → 取得 bot token
- 透過 `/setcommands` 設定指令清單（`short`、`list`、`stats`）

**步驟 2：在 Django admin 建立 API token**
- 登入 `/admin/` → ApiTokens → Add ApiToken
- 選擇自己的 user、填 `name`（例如 `telegram-bot`）→ Save
- **儲存後 admin 頁面會以 Django messages 顯示一次明文 token**——立刻複製，離開頁面後永遠看不到（DB 只存 hash）
- 若不慎漏抄 / 之後忘記，只能刪掉這把重新 issue

**步驟 3：Bot 端環境變數**
- bot 程式碼放在 repo 內（位置 `bot/` 或 `tgbot/`，由 bot impl spec 決定）
- 三個必要環境變數：
  - `TELEGRAM_BOT_TOKEN` — BotFather 給的 token
  - `URL_SHORTENER_API_TOKEN` — Django admin 產的明文 token
  - `URL_SHORTENER_API_BASE` — API base URL
    - dev: `http://127.0.0.1:8000/api/v1`
    - prod: `https://你的網域/api/v1`
- 加進 `.env.example`

**步驟 4：部署**
- 走 polling，bot 為長駐 process
- 部署選項（**留給 bot impl spec 決定**）：
  - 選項 A：systemd service on VPS
  - 選項 B：docker compose 多加一個 service
- 兩種都跟 Django 共用同一台 VPS，bot → API 走 localhost

### 11.2 Bot 指令對應 API

| TG 指令 | 對應 API | 失敗訊息來源 |
|---|---|---|
| `/short <url>` | `POST /api/v1/shorten/` | URL 格式錯 / 配額滿 / blocklist |
| `/list` | `GET /api/v1/urls/` | （讀取無錯誤情境） |
| `/stats <code>` | `GET /api/v1/stats/<code>/` | 短碼不存在 / 過期 |

### 11.3 不在這份 spec 的事項

- bot 內部 command handler 程式碼
- 具體 systemd unit / docker-compose service 內容
- bot 對 Telegram inline keyboard / message formatting 的 UX 設計
- bot 端錯誤訊息中文化策略

這些之後寫 `tg-bot-design.md` 時處理。

---

## 12. Future DRF Migration 對照

這份設計刻意對齊 DRF，未來換手只需做以下事：

| 現在 | DRF 版本 | 工作量 |
|---|---|---|
| `require_api_token` decorator | `BearerTokenAuthentication(TokenAuthentication)` subclass + 覆寫 `authenticate_credentials` 用 hash 查詢 | ~15 行 |
| `serialize_url()` function | `URLSerializer(ModelSerializer)` class | 重寫 ~30 行 |
| view 內手動 JSON 解析 | `serializer.is_valid()` | 刪 ~5 行 / view |
| `@ratelimit` decorator | `throttle_classes = [UserRateThrottle]` | trivial |
| `api_error()` helper | DRF custom exception handler | 改一處 |
| `Authorization: Bearer <token>` header | **沿用不變**（subclass 改 `keyword = "Bearer"`） | **bot 端 0 改動** |

**Service 層、Model 層、URL routing、Bot 程式碼**全部不用改。

---

## 13. Out of Scope（明列以避免 scope creep）

- DRF 引入（未來工作）
- Bot 程式碼實作（另開 `tg-bot-design.md`）
- Bot 部署細節（systemd unit、docker-compose service 內容）
- Token 過期機制 / token 自助管理 UI
- API 給其他使用者開放
- API 文件自動產生（OpenAPI/Swagger）
- Webhook 模式
- Click logs 列表 API（要看走 web 介面）
- Rate limit 視覺化 / metrics
- Bot inline keyboard / 多步驟對話流程

---

## 14. Security Notes（Operational）

Token model 本身的安全機制已寫在 §4（hash 儲存、明文只顯示一次、隔離 revoke）。以下是部署/運維面：

- **HTTPS only**：production 一律走 HTTPS（已由 nginx + Cloudflare Origin Cert 處理）
- **Token 不寫入 log**：`require_api_token` decorator 在處理失敗訊息時只能寫「token invalid」，**禁止寫出原始 header 內容**或 token 字串
- **Token 外洩處理流程**：Django admin 刪掉該把 token → 立刻失效 → 重新 issue 一把給 client
- **`.env` 檔權限**：bot 端的 `.env` 需設為 600（owner read/write only），避免同機其他 process 讀到