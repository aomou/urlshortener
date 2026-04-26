# VPS 部署指南（系統 Nginx + Docker + Cloudflare）

本文件記錄把這個專案部署到 VPS 的完整步驟。

## 架構概覽

```
                  ┌──────────────┐
   使用者 ──HTTPS──→ │  Cloudflare  │
                  └──────┬───────┘
                         │ HTTPS（Origin Cert，Full Strict）
                         ▼
                  ┌──────────────┐
                  │ 系統 Nginx   │  :80 / :443  （host 上跑）
                  │ (host)       │  ← /etc/ssl/cloudflare/ 的 cert
                  └──────┬───────┘
                         │ HTTP，proxy_pass
                         ▼
                  ┌──────────────┐
                  │  Gunicorn    │  127.0.0.1:8000  (Docker container)
                  │  + WhiteNoise│  ← 服務 /static/
                  │  (Django)    │
                  └──────┬───────┘
                         │
                         ▼
                  ┌──────────────┐
                  │  PostgreSQL  │  :5432  (Docker container)
                  └──────────────┘
```

- **Cloudflare**：終止使用者端 SSL、提供 CDN/DDoS 防護
- **系統 Nginx**（host）：反向代理、處理 Cloudflare 的 Origin Cert（Full Strict），整台 VPS 的「總入口」
- **Web container**（Gunicorn + WhiteNoise）：跑 Django，靜態檔由 WhiteNoise 直接 serve（內含 hashed 檔名 + brotli/gzip 預壓縮）
- **DB container**（PostgreSQL）：資料以 Docker volume 持久化

> 為什麼系統 nginx 而非 Docker nginx？因為這台 VPS 規劃放多個服務，系統 nginx 是「總入口」，每個服務一個 server block，比較容易擴充。

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

### 1.2 安裝 Nginx
```bash
sudo apt update
sudo apt install -y nginx
sudo systemctl enable nginx        # 開機自啟
```

> 多數 VPS image 預裝 nginx，這步可能已完成。

### 1.3 Clone 專案
```bash
sudo apt install -y git
git clone <your-repo-url> ~/urlshortener
cd ~/urlshortener
```

### 1.4 設定防火牆（UFW）
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
Cloudflare Dashboard → **SSL/TLS** → **Overview** → 設為 **Full (Strict)**

### 2.4 產生 Origin Certificate
1. SSL/TLS → **Origin Server** → **Create Certificate**
2. 選 RSA 2048、Hostname 填 `*.example.com, example.com`、有效期 15 年
3. **複製出來的兩段內容立刻存檔**（之後不再顯示）：
   - **Origin Certificate** → 存成 `origin.pem`
   - **Private Key** → 存成 `origin.key`

### 2.5 把 cert 安裝到 VPS（系統共用位置）
本機：
```bash
scp origin.pem origin.key user@<VPS IP>:~/
```
VPS 上：
```bash
sudo mkdir -p /etc/ssl/cloudflare
sudo mv ~/origin.pem ~/origin.key /etc/ssl/cloudflare/
sudo chown root:root /etc/ssl/cloudflare/origin.*
sudo chmod 644 /etc/ssl/cloudflare/origin.pem
sudo chmod 600 /etc/ssl/cloudflare/origin.key
```

> cert 放系統位置，未來別的服務也共用同一份（如果是 wildcard cert）。

---

## Step 3：環境變數

```bash
cd ~/urlshortener
cp .env.example .env
nano .env
```

要填的關鍵欄位：
```
SECRET_KEY=<產生一組亂數>
DEBUG=False
SITE_DOMAIN=example.com
DJANGO_SUPERUSER_PASSWORD=<passphrase>

DB_NAME=url_db
DB_USER=urlshort_admin
DB_PASSWORD=<強密碼>

GOOGLE_CLIENT_ID=<生產用那組>
GOOGLE_CLIENT_SECRET=<同上>
```

> Docker 部署不需要 DB_HOST 跟 DB_PORT（compose 寫死 `db:5432`），但有也不影響。

產生 SECRET_KEY：
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

---

## Step 4：Google OAuth 設定

[Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Credentials：

1. 建一個**生產用的** OAuth Client（不要用本機 dev 那組）
2. **Authorized redirect URIs** 加：
   ```
   https://example.com/accounts/google/login/callback/
   ```
3. 拿到 Client ID/Secret 填回 `.env`

---

## Step 5：設定系統 Nginx

### 5.1 複製專案內的 nginx 設定到系統位置
```bash
sudo cp ~/urlshortener/nginx/url-shortener.conf /etc/nginx/sites-available/url-shortener
```

### 5.2 把設定裡的網域填入
```bash
sudo sed -i 's/SITE_DOMAIN_PLACEHOLDER/example.com/g' /etc/nginx/sites-available/url-shortener
```
（把 `example.com` 換成你的實際網域）

### 5.3 啟用這個 site
```bash
sudo ln -s /etc/nginx/sites-available/url-shortener /etc/nginx/sites-enabled/
# 移除預設 site，避免攔截
sudo rm /etc/nginx/sites-enabled/default
```

### 5.4 測試並 reload
```bash
sudo nginx -t                     # 必須回 "syntax is ok" 和 "test is successful"
sudo systemctl reload nginx
```

> 任何時候改了 `/etc/nginx/sites-available/url-shortener`，跑 `sudo nginx -t && sudo systemctl reload nginx`。

---

## Step 6：跑 Docker stack

```bash
cd ~/urlshortener
chmod +x deploy.sh
./deploy.sh
```

`deploy.sh` 會：
1. 建立 Docker images（Dockerfile 內含 collectstatic）
2. 跑資料庫 migration
3. 啟動 web + db 兩個 container（web 只聽 `127.0.0.1:8000`）

### 驗證
```bash
docker compose ps                                # web / db 兩個都 Up
docker compose logs -f web --tail=30             # 看 gunicorn 啟動
curl -I http://127.0.0.1:8000                    # 從 host 直連 web，應該回 200/302
curl -I https://example.com                      # 走完整鏈路，應該回 200
```

打開瀏覽器 → `https://example.com` → 看到首頁 + 綠色鎖頭即成功。

---

## Step 7：建立 Django superuser（首次部署）

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
./deploy.sh                        # 會重 build image，新的靜態檔自動進去
```

### 改 nginx 設定
```bash
sudo nano /etc/nginx/sites-available/url-shortener
sudo nginx -t
sudo systemctl reload nginx
```

> 如果是改 repo 內的 `nginx/url-shortener.conf`，記得 `git pull` 後重新 `sudo cp` + `sed` + `nginx -t` + `reload`。

### 看 log
```bash
docker compose logs -f web              # Django / gunicorn
sudo tail -f /var/log/nginx/access.log  # nginx access
sudo tail -f /var/log/nginx/error.log   # nginx error
```

### 重啟單一 service
```bash
docker compose restart web
sudo systemctl restart nginx
```

### 進入 container
```bash
docker compose exec web bash
docker compose exec db psql -U urlshort_admin url_db
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
docker compose exec -T db pg_dump -U urlshort_admin url_db | gzip > backup_$(date +%F).sql.gz
```

---

## 疑難排解

| 症狀 | 可能原因 |
|------|---------|
| `502 Bad Gateway` | web container 沒起來，看 `docker compose logs web`；或 web 沒 listen 8000，看 `curl -I http://127.0.0.1:8000` |
| `400 Bad Request` (Django) | `SITE_DOMAIN` 沒設或設錯，settings.py 的 `ALLOWED_HOSTS` 不含實際網域 |
| Cloudflare 顯示 `Error 526` | Origin cert 過期或路徑錯，`ls -la /etc/ssl/cloudflare/`；或 nginx ssl_certificate 路徑寫錯 |
| OAuth callback 失敗 | Google Console 的 redirect URI 沒更新成 https 網域，或 client secret 填錯 |
| Click 紀錄全部是 Cloudflare IP | nginx 沒設 `real_ip_header` / `set_real_ip_from`，檢查 `/etc/nginx/sites-available/url-shortener` |
| 靜態檔 404 | image build 沒成功跑 collectstatic（rebuild：`docker compose build --no-cache web`） |
| `port 80 already in use` | 系統 nginx 跟 docker container 搶 port，本架構是系統 nginx 用 80，確認沒有舊的 docker 殘留 `docker compose down` |

---

## 安全強化（可選）

1. **限制只接受 Cloudflare 流量**：UFW 只允許 [Cloudflare IPv4/IPv6](https://www.cloudflare.com/ips/) 連 80/443
2. **Cloudflare WAF / Bot Fight Mode**：Dashboard 啟用
3. **fail2ban**：保護 SSH
4. **自動安全更新**：`sudo apt install unattended-upgrades`
