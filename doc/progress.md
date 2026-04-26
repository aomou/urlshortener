# Done

`2026-04-21-guest-mode-and-facebook-removal.md`

phase 1 data
    - 1.1 (users) add UserProfile model with auto-create signal
        - 舊資料不用保留，不做 data migration
    - 1.2 (shortener) add URLModel.expires_at
    - 1.3 (shortener) add RateLimitEvent model

phase 2 domain service
- 2.1 feat(shortener): add domain exceptions for expiry, blocklist, quota, ban
- 2.2 feat(shortener): add BlocklistService with local domain blocklist
- 2.3 feat(users): add UserService (guest creation, quota, lifetime, ban)
- 2.4 feat(shortener): add RateLimitService with auto-ban at 5 hits/10min
- 2.5 feat(shortener): enforce ban/blocklist/quota/expiry in URLService
    - test_quota_exceeded 數字 5 改用 GUEST_QUOTA 
- fix: 把 lifetime 倒數時間邏輯改成 expired_at 絕對時間

phase 3 Views & URL routing
- 3.1 feat(users): add guest login view with IP rate limit
- 3.2 feat(shortener): extract shorten view, wire rate limit + policy exceptions
- 3.3 feat(shortener): render expired page instead of redirecting past-expiry links

phase 4 Templates
- 4.1 feat(templates): new homepage with Google + Guest login
- 4.2 feat(templates): show guest expiry in navbar; drop Facebook mentions
- 4.3 feat(templates): show quota + expiry on /my-urls/

phase 5 Cleanup management commands
- 5.1 feat(shortener): add cleanup_expired_urls management command
- 5.2 feat(users): add cleanup_expired_guests management command

phase 6 Settins, Admin, Docs
- 6.1 chore: set TIME_ZONE=Asia/Taipei
- test: update POST endpoint from my_urls to shorten
- 6.2 docs: document guest mode and Facebook removal

fix: 訪客登入時不應該出現 log out 按鈕 -> 加 middleware
refactor(test): Service, View 分開

VPS + Nginx + Cloudflare 部署重構（第一輪：Docker nginx）
- e6e44a1 chore: remove Render-era build.sh
- 6a6da77 feat(deploy): containerize with Docker, Nginx, and Cloudflare (Full Strict)
- 10d8f1f refactor(settings): replace RENDER_EXTERNAL_HOSTNAME with SITE_DOMAIN; trust proxy headers
- 8525e2c feat(analytics): prefer CF-Connecting-IP for client IP resolution
- bc3a2a7 docs: add VPS deployment guide; refresh CLAUDE.md, README.md, progress.md
- b2394d1 fix(deploy): unify DB_* naming; clarify .env.example for local vs Docker

部署架構重構（第二輪：改成系統 nginx，uncommitted）
- 動機：VPS 預裝 nginx 且未來規劃多服務（再開 blog、其他工具），系統 nginx 當總入口才能擴充。Docker nginx 在多服務場景會撞 port。
- docker-compose.yml: 拿掉 nginx service 與 static_volume；web 改成 ports `127.0.0.1:8000:8000`，外部流量必須經系統 nginx
- deploy.sh: 拿掉 collectstatic 那行（Dockerfile build 已經做，無 named volume 不需重跑）
- nginx/default.conf.template + nginx/certs/.gitkeep: 刪除（容器版產物）
- nginx/url-shortener.conf（新）: 系統 nginx site config，部署時 cp 到 /etc/nginx/sites-available/，sed 把 SITE_DOMAIN_PLACEHOLDER 換成實際網域
- 靜態檔策略：改用 WhiteNoise（runtime 在 Django 容器內 serve）。host nginx 純 reverse proxy，不再碰 /static/
- cert 位置：從 ./nginx/certs/ 移到 /etc/ssl/cloudflare/（系統共用）
- .gitignore: 拿掉 nginx/certs/*.pem|*.key（不再放 repo）
- doc/deployment.md: 重寫，新架構步驟（裝 host nginx → 設 site config → docker compose）
- CLAUDE.md / README.md: 同步

# To-do

部署當下要做的（VPS 上、不是程式碼）
- 買網域，把 NS 指到 Cloudflare，建 A record（橘色雲）
- Cloudflare 產 Origin Cert，scp 進 nginx/certs/
- 重新申請一組生產用 Google OAuth Client ID/Secret
- VPS 上設 cron 跑 cleanup_expired_urls + cleanup_expired_guests

產品 / UX
- fix: 所有警告或說明文字都用英文顯示
- 新增 API endpoint
- UI improve

未來可加
- 作成 Telegram Bot 自用
- 儀表板加分析圖表 graph
- 顯示使用者自己的 local time (加 middleware)

# Notes

部署前要留意
- DJANGO_SUPERUSER_PASSWORD VPS 上第一次 createsuperuser 前要改強密碼
- nginx/url-shortener.conf 的 Cloudflare IP 段是寫死的，每半年到一年要對 https://www.cloudflare.com/ips/ 校正
- UFW 預計開放 80/443 給整個 Internet，攻擊者若知道 origin IP 可繞過 Cloudflare；deployment.md 有提到「鎖到 Cloudflare IP only」是進階選項，正式上線前值得做
- 靜態檔更新：改 CSS/JS 後跑 `./deploy.sh` 會 rebuild image，新檔自動進去；不要只 `docker compose restart web`（不會重 build）
- VPS 部署時 docker-compose 預設讀 `.env`，記得把 `.env.production` rename 或複製為 `.env`
- nginx/url-shortener.conf 是 repo 內的範本，部署時要 cp 到 /etc/nginx/sites-available/ 且 sed 換掉 SITE_DOMAIN_PLACEHOLDER；改 repo 範本後別忘了同步到系統路徑
