# Done

`2026-04-21-guest-mode-and-facebook-removal.md`

## phase 1 data

- (users) add UserProfile model with auto-create signal
    - 舊資料不用保留，不做 data migration
- (shortener) add URLModel.expires_at
- (shortener) add RateLimitEvent model

## phase 2 domain service



# To-do

改成自己的作品集
1. 移除 Facebook 登入功能
2. 新增訪客模式 but 限制流量
    - Rate limit 
    - URL 黑名單
    - 每日清理 job


3. 新增 API
4. VPS 部署設定
    - cronjob 自動刪除過期 URL + 訪客帳號

未來可加
- 作成 Telegram Bot 自用
- 儀表板加分析圖表 graph


# Notes