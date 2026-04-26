# VPS 部署指南（Docker + Nginx + Cloudflare）

本文件記錄把這個專案部署到 VPS 的完整步驟。

## 架構概覽

```
                  ┌──────────────┐
   使用者 ──HTTPS──→ │  Cloudflare  │
                  └──────┬───────┘
                         │ HTTPS（Origin Cert）
                         ▼
                  ┌──────────────┐
                  │   Nginx      │  :443  (Docker container)
                  │              │  ↳ /static/ 直接 serve
                  └──────┬───────┘
                         │ HTTP
                         ▼
                  ┌──────────────┐
                  │  Gunicorn    │  :8000 (web container)
                  │  (Django)    │
                  └──────┬───────┘
                         │
                         ▼
                  ┌──────────────┐
                  │  PostgreSQL  │  :5432 (db container)
                  └──────────────┘
```

- **Cloudflare**：終止使用者端 SSL、提供 CDN/DDoS 防護
- **Nginx**：反向代理、靜態檔服務、與 Cloudflare 之間的 TLS（Full Strict）
- **Gunicorn**：執行 Django 應用
- **PostgreSQL**：資料庫，資料以 Docker volume 持久化

---

## 前置條件

- 一台 VPS（Ubuntu 22.04 / 24.04 LTS 為佳）
- 一個網域（已可在 Cloudflare 管理 DNS）
- Cloudflare 帳號
- Google OAuth 用戶端（Google Cloud Console）

---

## Step 1：VPS 基本設定

### 1.1 安裝 Docker
```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# 重新登入讓 group 生效
```

### 1.2 安裝 git 與 clone 專案
```bash
sudo apt install -y git
git clone <your-repo-url> ~/urlshortener
cd ~/urlshortener
```

### 1.3 設定防火牆（UFW）
只開 80、443、SSH：
```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

> 進階：可以只允許 [Cloudflare IP](https://www.cloudflare.com/ips/) 連 80/443，避免被人繞過 CF 直接打 origin。本指南先省略。

---

## Step 2：Cloudflare 設定

### 2.1 把網域接到 Cloudflare
1. Cloudflare Dashboard → **Add a Site** → 輸入網域
2. 把 domain registrar 的 NS 改成 Cloudflare 給的兩組
3. 等 NS 生效（通常幾分鐘到幾小時）

### 2.2 DNS 紀錄
新增 A record 指到 VPS IP：

| Type | Name | Content | Proxy status |
|------|------|---------|--------------|
| A | `@` | `<VPS IP>` | **Proxied (橘色雲)** |
| A | `www` | `<VPS IP>` | **Proxied (橘色雲)** |

> 一定要 Proxied（橘色雲），不然 Cloudflare 不會處理 SSL 與 CDN。

### 2.3 SSL/TLS 模式
1. Cloudflare Dashboard → **SSL/TLS** → **Overview**
2. 設為 **Full (Strict)**

### 2.4 產生 Origin Certificate
1. SSL/TLS → **Origin Server** → **Create Certificate**
2. 選 RSA 2048、Hostname 填 `*.example.com, example.com`、有效期 15 年
3. **複製出來的兩段內容立刻存檔**（之後不再顯示）：
   - **Origin Certificate** → 存成 `origin.pem`
   - **Private Key** → 存成 `origin.key`

### 2.5 把 cert 上傳到 VPS
在你的本機：
```bash
scp origin.pem origin.key user@<VPS IP>:~/urlshortener/nginx/certs/
```
在 VPS 上：
```bash
chmod 600 ~/urlshortener/nginx/certs/origin.key
```

---

## Step 3：環境變數

### 3.1 建立 `.env`
```bash
cp .env.example .env
nano .env
```

需填寫：
```
SECRET_KEY=<產生一組亂數>
DEBUG=False
SITE_DOMAIN=example.com           # 你的網域
DJANGO_SUPERUSER_PASSWORD=<密碼>

DB_NAME=url_db
DB_USER=postgres
DB_PASSWORD=<強密碼>
DB_HOST=db                        # 注意：是 docker service 名，不是 localhost
DB_PORT=5432

GOOGLE_CLIENT_ID=<從 Google Cloud Console 取得>
GOOGLE_CLIENT_SECRET=<同上>
```

### 3.2 產生 SECRET_KEY
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

---

## Step 4：Google OAuth 設定

到 [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Credentials：

1. 編輯你的 OAuth Client
2. **Authorized redirect URIs** 加入：
   ```
   https://example.com/accounts/google/login/callback/
   ```
3. 儲存

---

## Step 5：部署

```bash
cd ~/urlshortener
chmod +x deploy.sh
./deploy.sh
```

`deploy.sh` 會：
1. 建立 Docker images
2. 跑資料庫 migration
3. `collectstatic` 把靜態檔放進 named volume（讓 nginx 能讀）
4. 啟動所有 services（web、db、nginx）

### 驗證
```bash
docker compose ps              # 三個 service 都該是 running
docker compose logs -f nginx   # 看 nginx 啟動有沒有錯
docker compose logs -f web     # 看 gunicorn
```

打開瀏覽器 → `https://example.com` → 應該看到首頁，且 URL 是綠色鎖頭。

---

## Step 6：建立 Django superuser（首次部署）

```bash
docker compose exec web python manage.py createsuperuser
```

之後可從 `https://example.com/admin/` 登入。

---

## 日常維運

### 更新程式碼
```bash
cd ~/urlshortener
git pull
./deploy.sh
```

### 看 log
```bash
docker compose logs -f web
docker compose logs -f nginx
```

### 重啟單一 service
```bash
docker compose restart web
```

### 進入 container
```bash
docker compose exec web bash
docker compose exec db psql -U postgres url_db
```

### 排程（cron）
清理過期短網址 / 訪客帳號：
```bash
crontab -e
```
加入：
```
# 每天 03:00 清理過期短網址與訪客帳號
0 3 * * * cd /home/<user>/urlshortener && docker compose exec -T web python manage.py cleanup_expired_urls >> /var/log/url_cleanup.log 2>&1
5 3 * * * cd /home/<user>/urlshortener && docker compose exec -T web python manage.py cleanup_expired_guests >> /var/log/guest_cleanup.log 2>&1
```

### 備份資料庫
```bash
docker compose exec -T db pg_dump -U postgres url_db | gzip > backup_$(date +%F).sql.gz
```

---

## 疑難排解

| 症狀 | 可能原因 |
|------|---------|
| `502 Bad Gateway` | `web` 沒起來，看 `docker compose logs web` |
| `400 Bad Request` (Django) | `SITE_DOMAIN` 沒設，或 `ALLOWED_HOSTS` 不含網域 |
| Cloudflare 顯示 `Error 526` | Origin cert 過期或路徑錯，檢查 `nginx/certs/` |
| OAuth callback 失敗 | Google Console 的 redirect URI 沒更新成 https 網域 |
| Click 紀錄全部是 Cloudflare IP | nginx 沒設 `real_ip_header` 或 `set_real_ip_from`，檢查 `nginx/default.conf.template` |
| 靜態檔 404 | 沒跑 `collectstatic`，或 named volume 沒建，重跑 `./deploy.sh` |

---

## 安全強化（可選）

1. **限制只接受 Cloudflare 流量**：在 UFW 只允許 [Cloudflare IPv4/IPv6](https://www.cloudflare.com/ips/) 連 80/443
2. **Cloudflare WAF / Bot Fight Mode**：在 Cloudflare Dashboard 啟用
3. **fail2ban**：保護 SSH
4. **自動安全更新**：`sudo apt install unattended-upgrades`
