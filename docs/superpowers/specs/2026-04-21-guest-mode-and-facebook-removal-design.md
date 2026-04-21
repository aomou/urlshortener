# Guest Mode + Facebook Removal — Design

**Date:** 2026-04-21
**Status:** Approved (design phase)
**Batch:** 1 of 3 (Batch 2 = DRF API + Telegram bot guide; Batch 3 = VPS deployment)

## Goal

Make the URL shortener usable as a portfolio demo by allowing visitors to try the service without OAuth login, while preventing the service from being abused as a phishing host or becoming a real free-tier service people depend on.

- Visitors click a **Try as Guest** button, receive a throwaway account (24h lifetime), and get the full experience including click analytics.
- Guest accounts and their URLs are auto-purged after expiry.
- Google-logged-in users get 7-day URLs (not permanent), so the service never becomes a real link-shortening service.
- Admin (`is_staff=True`) is the only role that can create permanent URLs; no admin-only UI.
- Facebook OAuth is removed in this batch.

## Scope

### In Scope
1. Remove Facebook OAuth from code, templates, env, and docs.
2. New `users` app with `UserProfile` (OneToOne to `User`): `is_guest`, `is_banned`, `expires_at`.
3. Add `URLModel.expires_at` (nullable).
4. Guest login flow: button → random `guest_<hex>` user → Django session login → `/my-urls/`.
5. URL lifetime rules enforced server-side by identity:
   - Guest → `profile.expires_at` (24h from guest creation)
   - Google → `now + 7d`
   - Admin → `null` (permanent)
6. Redirect view checks expiry; expired URLs render `expired.html` (not 404).
7. Local domain blocklist (`shortener/data/blocklist.txt`) checked on URL creation.
8. Per-user **active URL quota** (simultaneous non-expired URLs): Guest 5 / Google 10 / Admin unlimited.
9. Rate limits: URL creation 5/min per user; guest account creation 1/hour per IP.
10. Auto-ban: 5 rate-limit hits within 10 minutes → `profile.is_banned=True`; manual unban via Django admin.
11. Management commands for cleanup (cron scheduling deferred to Batch 3):
    - `cleanup_expired_urls` — deletes URLs with `expires_at < now`.
    - `cleanup_expired_guests` — deletes guest users with `profile.expires_at < now` (cascades URLs + ClickLogs).
12. `settings.TIME_ZONE` → `"Asia/Taipei"` so datetimes render in local time.

### Out of Scope
- Click-through warning interstitial page.
- IP ban / `BannedIP` model.
- Google Safe Browsing API (local blocklist only for now).
- Admin-only UI (e.g., custom expiry picker).
- Guest-to-Google account upgrade flow.
- URL expiry extension.
- DRF API (Batch 2).
- VPS deployment config (Batch 3).

## Architecture

Follows CLAUDE.md "Thin Views, Fat Services". All business logic lives in service layer; views catch domain exceptions and map to HTTP responses.

### Apps
- `shortener/` — URL, ClickLog models; URLService, AnalyticsService, BlocklistService, RateLimitService.
- `users/` — (rebuilt) UserProfile model; UserService.
- `core/` — settings, urls.

## Data Model

### New: `users.UserProfile`
```python
class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    is_guest = models.BooleanField(default=False)
    is_banned = models.BooleanField(default=False)
    expires_at = models.DateTimeField(null=True, blank=True)  # only set for guests
    created_at = models.DateTimeField(auto_now_add=True)
```
- `post_save` signal on `User` creates a default profile (`is_guest=False`, `expires_at=None`).
- Guest login flow overwrites profile to `is_guest=True, expires_at=now+24h` after user creation.

### New: `shortener.RateLimitEvent`
```python
class RateLimitEvent(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="rate_limit_events")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
```
- Each 429 trigger writes one row; `RateLimitService.register_hit` queries last 10 minutes to decide ban.

### Modified: `shortener.URLModel`
- Add `expires_at = models.DateTimeField(null=True, blank=True, db_index=True)`.
- No `is_expired` flag — expiry is a pure timestamp comparison.

### Migrations
1. `users/migrations/0001_initial.py` — create `UserProfile`; data migration backfills profile for existing users (`is_guest=False`, `expires_at=None`).
2. `shortener/migrations/XXXX_urlmodel_expires_at.py` — add `expires_at`; existing rows get `null` (compatible with admin/permanent semantics).
3. `shortener/migrations/XXXX_ratelimitevent.py` — create `RateLimitEvent`.

## Services

### `users.services.UserService`
- `create_guest_user() -> User`  # 產生訪客帳號
  - Generate `username = f"guest_{secrets.token_hex(4)}"` (retry on `IntegrityError` up to 3 times).
  - `User.objects.create(username=..., email="")` + `set_unusable_password()`.
  - Update auto-created profile: `is_guest=True, expires_at=now+timedelta(hours=24)`.
  - Return the user.
- `get_quota(user) -> int | float`  # active url 剩餘額度
  - Admin (`is_staff`) → `float("inf")`
  - Guest (`profile.is_guest`) → 5
  - Otherwise → 10
  - Semantics: maximum number of **active (non-expired)** URLs the user can hold at once. Expired-but-not-yet-cleaned URLs do NOT count toward this cap.
- `get_url_lifetime(user) -> timedelta | None`  # 新網址只能活多久
  - Admin → `None` (permanent)
  - Guest → `profile.expires_at - now` (aligns URL expiry with account expiry)
  - Google → `timedelta(days=7)`
- `ban_user(user, request)` — set `profile.is_banned=True`, call `auth.logout(request)`.  # 封鎖

### `shortener.services.BlocklistService`
- `is_blocked(url: str) -> bool` # 建立 url 黑名單 -> 禁止二次轉址、垃圾惡意網址
  - Parse hostname via `urllib.parse.urlparse`.
  - Strip leading `www.`, lowercase.
  - Exact match against blocklist set loaded from `shortener/data/blocklist.txt`.
- Blocklist file: one domain per line, `#` comments allowed; loaded once at module import.
- Content seed: common link shorteners (`bit.ly`, `t.co`, `tinyurl.com`, etc.) + a few well-known phishing domains. Committed to repo.

### `shortener.services.RateLimitService`
- `register_hit(user)` — create `RateLimitEvent(user=user)`; count events for this user in last 10 minutes; if `>= 5`, call `UserService.ban_user`.
- Called by the view after `django-ratelimit` raises `Ratelimited` (decorator blocks the view, so the counter-increment happens in the handler, not in the decorator).

### `shortener.services.URLService.get_or_create_short_url`
Signature unchanged: `(user, original_url) -> (URLModel, bool)`. New checks (in order):
1. `UserBannedError` if `user.profile.is_banned`.  # 檢查是否被封鎖
2. `BlockedDomainError` if `BlocklistService.is_blocked(original_url)`.  # 建立網址時就檢查是否在黑名單內
3. `QuotaExceededError` if active URL count `>= UserService.get_quota(user)`. Active = `URLModel.objects.filter(user=user).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now)).count()`.
4. Compute `expires_at`:
   - `lifetime = UserService.get_url_lifetime(user)`
   - `expires_at = None if lifetime is None else now + lifetime`
5. Sqids encode + save URL with `expires_at`.

### `shortener.services.URLService.get_url_by_code`
New: raise `UrlExpiredError` if `url.expires_at is not None and url.expires_at < now`.

## Domain Exceptions

`shortener/exceptions.py`:
```python
class URLServiceError(Exception): ...
class UrlNotFoundError(URLServiceError): ...
class UrlExpiredError(URLServiceError): ...
class BlockedDomainError(URLServiceError): ...
class QuotaExceededError(URLServiceError): ...
class UserBannedError(URLServiceError): ...
```

### View → Exception Mapping
| Exception | View Response |
|---|---|
| `UrlNotFoundError` | 404 |
| `UrlExpiredError` | 200 render `expired.html` |
| `BlockedDomainError` | Form error; redirect back to `/my-urls/` with `messages.error` |
| `QuotaExceededError` | Form error; message includes quota number |
| `UserBannedError` | 403 render `banned.html`; force logout |
| `Ratelimited` (from django-ratelimit) | 429 render `rate_limited.html`; call `RateLimitService.register_hit` |

## User Flows

### Flow A — Guest Login
1. Visitor `POST /accounts/guest-login/` (CSRF required; public).
2. View has `@ratelimit(key="ip", rate="1/h", block=True)`.
3. `UserService.create_guest_user()` → `login(request, user)` → redirect `/my-urls/`.
4. Navbar now shows `Guest • expires 2026-04-22 03:00` (absolute local time; no JS countdown).

### Flow B — Create Short URL (unified for all identities)
1. `POST /shorten/` with `@login_required` + `@ratelimit(key="user", rate="5/m", block=True)`.
2. View calls `URLService.get_or_create_short_url(request.user, url)`.
3. On `Ratelimited` caught in a wrapper: call `RateLimitService.register_hit(user)` then render 429.
4. On other exceptions: map per table above.
5. On success: `messages.success` + redirect `/my-urls/`.

### Flow C — Short URL Redirect
1. `GET /<code>/`.
2. `URLService.get_url_by_code(code)`:
   - Not found → 404.
   - Expired → `UrlExpiredError` → render `expired.html` (no click recorded).
3. `AnalyticsService.record_click(url, request)` → 302 to `original_url`.

### Flow D — Auto Ban
1. User hits rate limit → view renders 429 and calls `RateLimitService.register_hit`.
2. If 5 events in last 10 min → `UserService.ban_user` → `profile.is_banned=True`, logout.
3. Subsequent requests from this user to any login-required view → 403.
4. Admin manually toggles `is_banned=False` from Django admin to restore.

## UX / Templates

### Homepage `/`
- Unauthenticated: two buttons — **Login with Google**, **Try as Guest** — plus a brief service description.
- Authenticated: view returns `redirect("/my-urls/")`.

### Navbar (`templates/base.html`)
- Guest user: show `Guest • expires {{ user.profile.expires_at|date:"Y-m-d H:i" }}` + tooltip "Your account and URLs will be deleted at expiry".
- Google user: existing provider display.
- Remove Facebook provider label logic.

### `/my-urls/`
- Per-URL row shows `expires_at` formatted as absolute local datetime; `null` renders as "Permanent".
- Creation form shows quota status: `3 of 5 active URLs`.
- Form help text differs by identity: "Guest links expire at <time>" / "Links expire 7 days after creation" / (none for admin).

### New Templates
- `shortener/templates/shortener/expired.html` — "This link has expired."
- `shortener/templates/shortener/rate_limited.html` — "Too many requests. Try again later."
- `users/templates/users/banned.html` — "This account has been suspended."

### Removed
- All Facebook-related template fragments (buttons, icons, provider display strings).

## Settings Changes

- `INSTALLED_APPS`:
  - Remove `allauth.socialaccount.providers.facebook`.
  - Add `users` (rebuilt app).
- `SOCIALACCOUNT_PROVIDERS`: remove `facebook` block.
- `TIME_ZONE`: `"UTC"` → `"Asia/Taipei"`.
- Add to `INSTALLED_APPS` / `MIDDLEWARE` as required by `django-ratelimit` (`django_ratelimit` lib).

## Dependencies (new)

- `django-ratelimit` — rate limiting decorators.
- No new cache backend required; `django-ratelimit` defaults to Django cache, which `LocMemCache` handles (single-worker deployments acceptable for this portfolio).

## Facebook Removal Checklist

1. `core/settings.py`: remove from `INSTALLED_APPS` and `SOCIALACCOUNT_PROVIDERS`.
2. `.env.example`: delete `FACEBOOK_CLIENT_ID`, `FACEBOOK_SECRET_KEY`.
3. `.env` (local, not in repo): reminder only — user removes manually.
4. Templates: remove all `facebook` mentions (login buttons, icons, provider display text).
5. `README.md`: drop Facebook setup section; OAuth section becomes Google-only.
6. `doc/url_shortener_spec.md`, `doc/development_roadmap.md`: annotate "Facebook login removed 2026-04-21".
7. Post-deploy manual step: delete Facebook `SocialApp` row from Django admin (data, not schema).

## Cleanup Commands

Management commands (runnable as `python manage.py <name>`), scheduling wired up in Batch 3:

### `cleanup_expired_urls`
```python
URLModel.objects.filter(expires_at__lt=timezone.now()).delete()
```
Prints count deleted.

### `cleanup_expired_guests`
```python
User.objects.filter(
    profile__is_guest=True,
    profile__expires_at__lt=timezone.now(),
).delete()
```
Cascade drops URLs and ClickLogs. Prints count deleted.

Both commands are idempotent and safe to run on any schedule.

## Testing Strategy

Primary focus: service layer. Views and templates tested for authorization and routing, not pixel-level rendering.

### `UserService`
- `create_guest_user` → username matches `guest_[0-9a-f]{8}`, profile has `is_guest=True` and `expires_at` ≈ now+24h.
- `get_quota` returns correct values for guest / Google / admin.
- `get_url_lifetime` returns correct value for each identity.
- `ban_user` sets `is_banned=True` and session is cleared.

### `URLService.get_or_create_short_url`
- Guest → URL `expires_at == profile.expires_at`.
- Google → URL `expires_at ≈ now + 7d`.
- Admin → URL `expires_at is None`.
- Over quota → `QuotaExceededError`. Test that expired-but-not-cleaned URLs do NOT count toward the cap (create user at quota with all URLs expired → new creation succeeds).
- Blocklist hit → `BlockedDomainError`.
- Banned user → `UserBannedError`.

### `URLService.get_url_by_code`
- Expired URL → `UrlExpiredError`.
- Missing URL → `UrlNotFoundError`.

### `BlocklistService`
- Exact hostname match; `evil.com` blocked, `notevil.com` not.
- `www.` prefix normalized.
- Case-insensitive.

### `RateLimitService.register_hit`
- Five hits within 10 minutes triggers ban.
- Events outside window do not count.

### Redirect view
- Unexpired → 302 + click recorded.
- Expired → 200 render expired; no click recorded.
- Missing → 404.

### Cleanup commands
- `cleanup_expired_urls`: seed mix of expired/unexpired, run, assert only unexpired remain.
- `cleanup_expired_guests`: seed expired guest with URLs + clicks, run, assert user + URLs + clicks all gone via cascade.

### Views (minimal)
- `/` unauth renders both login buttons; authed redirects to `/my-urls/`.
- `/accounts/guest-login/` exceeding IP rate limit returns 429.
- `/my-urls/` returns 403 for banned user.

### Not Tested
- Sqids encode/decode (third-party).
- `django-allauth` OAuth flow (third-party).
- Template pixel-level rendering.

## Known Limitations

- **Banned guest can create a new guest account.** Because guests get fresh User rows and we deliberately do not track IPs for banning, a banned guest could click "Try as Guest" again and bypass their ban. The only throttle is the per-IP 1/hour guest-creation rate limit. Accepted tradeoff — within portfolio scope the 1/hour ceiling is sufficient; upgrading to IP ban is explicitly out of scope.
- **Ban enforcement is service-level, not middleware-level.** `URLService.get_or_create_short_url` raises `UserBannedError` for banned users. Other views (list own URLs, view own stats) do not check ban status, because those are read-only and pose no abuse risk. This keeps ban logic in one place.
- **Rate limit counters use `LocMemCache` by default.** If the app ever deploys with multiple worker processes, each worker keeps its own counter and effective rate limits multiply by worker count. For this portfolio's single-worker deployment this is acceptable; if Batch 3 introduces multiple workers, switch `django-ratelimit` to a shared backend (Redis / DB cache).

## Open Questions / Deferred

- **Cron scheduling mechanism** — deferred to Batch 3 (VPS deployment). Management commands are ready to plug into systemd timers or cron.
- **Blocklist content maintenance** — for now, a static seed committed to repo. If the blocklist ever needs dynamic updates, consider a DB-backed model in a later batch.
- **Session TTL alignment** — Django session default is 2 weeks. For guests, we rely on the cleanup command deleting the User (which invalidates the session) rather than adjusting `SESSION_COOKIE_AGE`. If a guest's session outlives their user by a few minutes between cleanup runs, `request.user` resolves to `AnonymousUser` naturally — acceptable.
