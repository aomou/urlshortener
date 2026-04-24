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

# To-do

dockerize
- Add Docekrfile, docker-compose.yml, .dockerignore, deploy.sh
- 檢查 .env, .env.production
- 改 settings

fix: 所有警告或說明文字都用英文顯示

- VPS 部署設定
    - 改用 Nginx
    - cronjob 自動刪除過期 URL + 訪客帳號
    - 重新申請一組 Google Client key

- 新增 API endpoint
- UI improve

未來可加
- 作成 Telegram Bot 自用
- 儀表板加分析圖表 graph
- 顯示使用者自己的 local time (加 middleware)

# Notes