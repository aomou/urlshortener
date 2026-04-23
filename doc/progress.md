# Done

`2026-04-21-guest-mode-and-facebook-removal.md`

## phase 1 data

- (users) add UserProfile model with auto-create signal
    - 舊資料不用保留，不做 data migration
- (shortener) add URLModel.expires_at
- (shortener) add RateLimitEvent model

## phase 2 domain service

- feat(shortener): add domain exceptions for expiry, blocklist, quota, ban
- feat(shortener): add BlocklistService with local domain blocklist
- feat(users): add UserService (guest creation, quota, lifetime, ban)
- feat(shortener): add RateLimitService with auto-ban at 5 hits/10min
- feat(shortener): enforce ban/blocklist/quota/expiry in URLService
    - test_guest_url_expires_with_guest 測試先不加
    - test_quota_exceeded 數字 5 改用 GUEST_QUOTA 
- fix: 把 lifetime 倒數時間邏輯改成 expired_at 絕對時間

## phase 3 Views & URL routing

- feat(users): add guest login view with IP rate limit
- feat(shortener): extract shorten view, wire rate limit + policy exceptions
- feat(shortener): render expired page instead of redirecting past-expiry links

## phase 4 Templates

- feat(templates): new homepage with Google + Guest login
- feat(templates): show guest expiry in navbar; drop Facebook mentions


# To-do

改成自己的作品集
1. 移除 Facebook 登入功能
2. 新增訪客模式 but 限制流量
    - Rate limit 
    - URL 黑名單
    - 每日清理 job

3. UI improve
4. 新增 API endpoint
5. VPS 部署設定
    - cronjob 自動刪除過期 URL + 訪客帳號

未來可加
- 作成 Telegram Bot 自用
- 儀表板加分析圖表 graph


# Notes