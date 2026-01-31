# 開發日程計劃

**專案**：Django 縮網址服務
**版本**：MVP v0.1.0
**預計總時間**：約 21 小時
**開發模式**：連續開發（一次完成所有階段）

---

## Phase 0: 環境配置與基礎設定

**預計時間**：2 小時
**目標**：完成 Django 專案的基礎配置，切換到 PostgreSQL，設定 django-allauth

### 任務清單

- [ ] **資料庫設定**
  - 建立 PostgreSQL 資料庫 `url_shortener_db`
  - 配置 `.env` 環境變數（DATABASE_URL, SECRET_KEY）
  - 修改 `settings.py` 使用 PostgreSQL 和 python-dotenv

- [ ] **Django-allauth 配置**
  - 在 `INSTALLED_APPS` 加入 allauth 相關模組
  - 設定 `AUTHENTICATION_BACKENDS`
  - 設定 `django.contrib.sites` 和 `SITE_ID = 1`
  - 配置登入/登出重定向 URL

- [ ] **中間件與靜態檔案**
  - 加入 `allauth.account.middleware.AccountMiddleware`
  - 配置 WhiteNoise（MIDDLEWARE 和 STATIC 設定）
  - 設定 `STATIC_ROOT` 和 `STATICFILES_STORAGE`

- [ ] **初始化資料庫**
  - 執行 `python manage.py migrate`
  - 建立 superuser

### 修改的檔案

```
core/settings.py        # 主要配置檔
.env                    # 環境變數（新增）
```

### 驗收標準

- ✅ 可以成功執行 `python manage.py runserver`
- ✅ 可以訪問 `/admin/` 並用 superuser 登入
- ✅ PostgreSQL 連線正常
- ✅ Django-allauth 的 migrations 已執行

---

## Phase 1: OAuth 登入系統

**預計時間**：4 小時
**目標**：實作 Google 和 Facebook OAuth 登入功能

### 任務清單

- [ ] **OAuth 應用程式設定**
  - 在 Google Cloud Console 建立 OAuth 2.0 憑證
  - 在 Facebook Developers 建立應用程式
  - 在 Django Admin 新增 Social Application（Google/Facebook）

- [ ] **URL 路由配置**
  - 在 `core/urls.py` 加入 allauth 路由
  - 設定首頁路由 `/`

- [ ] **首頁 Template**
  - 建立 `templates/base.html`（base template）
  - 建立 `templates/home.html`（登入頁）
  - 加入 Google 和 Facebook 登入按鈕
  - 簡單的 Landing page 說明

- [ ] **登入流程測試**
  - 測試 Google OAuth 流程
  - 測試 Facebook OAuth 流程
  - 確認使用者資料正確寫入資料庫

### 建立/修改的檔案

```
core/urls.py                    # URL 路由
core/settings.py                # TEMPLATES 路徑設定
templates/base.html             # 基礎模板（新增）
templates/home.html             # 首頁/登入頁（新增）
```

### 驗收標準

- ✅ 訪問 `/` 可以看到登入頁面
- ✅ 點擊「Google 登入」可以跳轉到 Google 授權頁
- ✅ 點擊「Facebook 登入」可以跳轉到 Facebook 授權頁
- ✅ 授權成功後會建立使用者並重定向到 `/my-urls/`（暫時 404 正常）

---

## Phase 2: URL 縮短核心功能

**預計時間**：6 小時
**目標**：實作短網址建立、列表、重定向功能

### 任務清單

#### 2.1 資料模型定義（1 小時）

- [ ] **定義 Models**
  - 在 `shortener/models.py` 定義 `URLModel`
  - 在 `shortener/models.py` 定義 `ClickLog`
  - 設定適當的索引（`short_code` 加 `db_index=True`）

- [ ] **執行 Migrations**
  - 執行 `python manage.py makemigrations`
  - 執行 `python manage.py migrate`

#### 2.2 Service 層實作（2.5 小時）

- [ ] **建立 Sqids 編碼器**
  - 在 `shortener/services.py` 建立全域 Sqids 實例
  - 設定 `min_length=6`, `alphabet`, `blocklist`

- [ ] **URLService 實作**
  - `create_short_url(user, original_url)` - 建立短網址
  - `get_url_by_code(code)` - 解碼並查詢 URL
  - `get_user_urls(user)` - 取得使用者的 URL 列表

- [ ] **自訂異常**
  - 建立 `shortener/exceptions.py`
  - 定義 `URLServiceError`, `UrlNotFoundError`, `AccessDeniedError`

#### 2.3 View 與 Template（2.5 小時）

- [ ] **我的網址頁 View**
  - 在 `shortener/views.py` 實作 `my_urls` view
  - 處理 GET（顯示列表）和 POST（建立短網址）
  - 加入 `@login_required` 裝飾器

- [ ] **重定向 View**
  - 實作 `redirect_short_url` view
  - 呼叫 `URLService.get_url_by_code()`
  - 執行 302 重定向（暫不記錄點擊）

- [ ] **Templates**
  - 建立 `templates/shortener/my_urls.html`
  - 顯示短網址列表（短碼、原網址、建立時間、點擊次數）
  - 建立短網址的表單

- [ ] **URL 路由**
  - 在 `core/urls.py` 加入 shortener 路由
  - 確保 `/<code>/` 路由放在最後

### 建立/修改的檔案

```
shortener/models.py             # URLModel, ClickLog
shortener/services.py           # URLService（新增）
shortener/exceptions.py         # 自訂異常（新增）
shortener/views.py              # my_urls, redirect_short_url
templates/shortener/my_urls.html  # 我的網址頁（新增）
core/urls.py                    # 加入 shortener 路由
```

### 驗收標準

- ✅ 登入後訪問 `/my-urls/` 可以看到列表頁
- ✅ 可以在表單輸入長網址並建立短網址
- ✅ 建立成功後會顯示在列表中
- ✅ 點擊短網址連結會正確重定向到原網址
- ✅ 訪問不存在的短碼會顯示 404 頁面

---

## Phase 3: 統計與分析功能

**預計時間**：4 小時
**目標**：實作點擊記錄、統計詳情頁、IP 匿名化

### 任務清單

#### 3.1 AnalyticsService 實作（2 小時）

- [ ] **點擊記錄功能**
  - 在 `shortener/services.py` 實作 `AnalyticsService`
  - `record_click(url, request)` - 記錄點擊
  - 使用 `django-ipware` 取得真實 IP
  - 使用 `django-user-agents` 解析 User-Agent
  - 記錄完整 IP 到資料庫

- [ ] **統計資料彙整**
  - `get_url_stats(url_obj)` - 取得統計數據
  - 聚合點擊總數
  - 取得點擊記錄列表（按時間倒序）

- [ ] **IP 匿名化工具**
  - 實作 `anonymize_ip(ip_str)` 函數
  - 處理 IPv4（遮蔽最後一段）
  - 處理 IPv6（遮蔽後 80 位元）

#### 3.2 統計頁面實作（2 小時）

- [ ] **統計詳情頁 View**
  - 在 `shortener/views.py` 實作 `url_stats` view
  - 驗證擁有者權限（`url.user == request.user`）
  - 呼叫 `AnalyticsService.get_url_stats()`
  - 在 template 中使用 `anonymize_ip()` 顯示匿名化 IP

- [ ] **Template**
  - 建立 `templates/shortener/url_stats.html`
  - 顯示短網址資訊（短碼、原網址、建立時間）
  - 顯示總點擊次數
  - 顯示點擊記錄表格（時間、IP、瀏覽器、OS、裝置、Referer）

- [ ] **整合點擊記錄**
  - 修改 `redirect_short_url` view
  - 在重定向前呼叫 `AnalyticsService.record_click()`

- [ ] **我的網址頁更新**
  - 在列表中顯示點擊次數
  - 加入「查看統計」按鈕/連結

### 建立/修改的檔案

```
shortener/services.py           # 新增 AnalyticsService
shortener/views.py              # 新增 url_stats view, 修改 redirect_short_url
templates/shortener/url_stats.html  # 統計詳情頁（新增）
templates/shortener/my_urls.html  # 加入查看統計連結
core/urls.py                    # 加入 stats 路由
```

### 驗收標準

- ✅ 訪問短網址會記錄點擊（IP、User-Agent、Referer）
- ✅ 可以訪問 `/stats/<code>/` 查看統計
- ✅ 非擁有者訪問統計頁會被拒絕（403 或 404）
- ✅ 統計頁正確顯示點擊記錄
- ✅ IP 位址以匿名化形式顯示（如 192.168.1.0）
- ✅ 瀏覽器、OS、裝置類型正確解析

---

## Phase 4: 測試與程式碼品質

**預計時間**：3 小時
**目標**：撰寫測試、執行 linting、修正問題

### 任務清單

#### 4.1 Service 層測試（1.5 小時）

- [ ] **URLService 測試**
  - 測試 `create_short_url()` 建立流程
  - 測試 Sqids 編碼/解碼邏輯
  - 測試 `get_url_by_code()` 查詢邏輯
  - 測試無效短碼的異常處理

- [ ] **AnalyticsService 測試**
  - 測試 `record_click()` 記錄邏輯
  - 測試 IP 匿名化函數
  - 測試 User-Agent 解析

#### 4.2 View 層測試（1 小時）

- [ ] **權限測試**
  - 測試未登入使用者訪問 `/my-urls/` 會重定向
  - 測試非擁有者訪問統計頁會被拒絕

- [ ] **重定向測試**
  - 測試短網址重定向功能
  - 測試不存在的短碼回傳 404

#### 4.3 程式碼品質（0.5 小時）

- [ ] **執行格式化與檢查**
  - 執行 `black .` 格式化程式碼
  - 執行 `ruff check --fix .` 修正問題
  - 檢查並修正 linting 警告

- [ ] **執行測試**
  - 執行 `python manage.py test`
  - 確保所有測試通過

### 建立/修改的檔案

```
shortener/tests.py              # Service 和 View 測試
```

### 驗收標準

- ✅ 所有測試通過
- ✅ Ruff 檢查無錯誤
- ✅ Black 格式化完成
- ✅ 程式碼符合 PEP8 規範

---

## Phase 5: 部署準備

**預計時間**：2 小時
**目標**：配置生產環境設定、準備 Render 部署

### 任務清單

#### 5.1 生產環境配置（1 小時）

- [ ] **Settings 優化**
  - 分離開發/生產環境設定
  - 設定 `ALLOWED_HOSTS` 從環境變數讀取
  - 設定 `DEBUG` 從環境變數讀取
  - 確保 `SECRET_KEY` 使用環境變數

- [ ] **靜態檔案配置**
  - 確認 WhiteNoise 設定正確
  - 測試 `python manage.py collectstatic`

- [ ] **Django Admin 設定**
  - 在 `shortener/admin.py` 註冊 URLModel 和 ClickLog
  - 設定適當的 list_display 和 search_fields

#### 5.2 Render 部署準備（1 小時）

- [ ] **文件更新**
  - 確認 `doc/url_shortener_spec.md` 的部署章節正確
  - 確認 `CLAUDE.md` 的部署資訊正確

- [ ] **環境變數清單**
  - 列出需要在 Render 設定的環境變數
  - 撰寫環境變數說明（不含實際值）

- [ ] **部署檢查清單**
  - Build Command: `pip install && python manage.py collectstatic --noinput && python manage.py migrate`
  - Start Command: `gunicorn core.wsgi:application`
  - OAuth 回調網址提醒

### 建立/修改的檔案

```
core/settings.py                # 環境變數設定
shortener/admin.py              # Admin 註冊
doc/deploy_checklist.md         # 部署檢查清單（新增，可選）
```

### 驗收標準

- ✅ `collectstatic` 執行無誤
- ✅ 所有環境變數都透過 `.env` 或環境變數管理
- ✅ Django Admin 可以查看和管理 URLModel、ClickLog
- ✅ 部署文件完整且正確

---

## 時間預估總結

| 階段 | 預計時間 | 累積時間 |
|------|---------|---------|
| Phase 0: 環境配置 | 2 小時 | 2 小時 |
| Phase 1: OAuth 登入 | 4 小時 | 6 小時 |
| Phase 2: URL 縮短 | 6 小時 | 12 小時 |
| Phase 3: 統計分析 | 4 小時 | 16 小時 |
| Phase 4: 測試品質 | 3 小時 | 19 小時 |
| Phase 5: 部署準備 | 2 小時 | 21 小時 |

**總計：約 21 小時**

---

## 注意事項

### 開發順序
- ⚠️ 必須按照 Phase 順序進行，後面的階段依賴前面的功能
- ⚠️ 每個 Phase 完成後建議 commit 一次，方便回溯

### Git Commit 建議
- Phase 0: `feat: configure django settings and postgresql`
- Phase 1: `feat: implement oauth login with google and facebook`
- Phase 2: `feat: implement url shortening and redirect`
- Phase 3: `feat: implement analytics and click tracking`
- Phase 4: `test: add tests and improve code quality`
- Phase 5: `chore: prepare for render deployment`

### 可能遇到的問題
1. **OAuth 測試**：需要設定正確的回調網址（`http://localhost:8000/accounts/google/login/callback/`）
2. **Sqids 短碼衝突**：理論上不會發生，但建議加入 try-except 處理
3. **IP 取得問題**：本地開發可能取得 `127.0.0.1`，需要在 Render 環境測試
4. **時區問題**：確認 `settings.py` 的 `TIME_ZONE` 設定正確（建議 `Asia/Taipei`）

---

## 完成後的功能清單

- ✅ Google OAuth 登入
- ✅ Facebook OAuth 登入
- ✅ 建立短網址
- ✅ 短網址重定向（302）
- ✅ 我的網址列表頁
- ✅ 點擊統計記錄
- ✅ 統計詳情頁（含 IP 匿名化）
- ✅ 瀏覽器/OS/裝置解析
- ✅ Referer 記錄
- ✅ 擁有者權限驗證
- ✅ Service Layer 架構
- ✅ 單元測試與整合測試
- ✅ 程式碼品質檢查（Black + Ruff）
- ✅ 部署準備（Render）
