# Guest Mode + Facebook Removal — Implementation Plan

> **Learning-oriented plan.** Each task says WHAT to do and WHY, with enough concrete detail to execute but not every keystroke. Commit checkpoints are markers — run `git commit` yourself when you reach one. See `docs/superpowers/specs/2026-04-21-guest-mode-and-facebook-removal-design.md` for the approved design.

**Goal:** Let visitors try the service via a 24h guest account, add abuse controls (quota, rate limit, auto-ban, blocklist), and remove Facebook OAuth.

**Tech Stack:** Django 6, `django-allauth`, `django-ratelimit`, Sqids, PostgreSQL, `uv`.

**Test runner:** `python manage.py test` (Django built-in). Tests live in `shortener/tests.py` and `users/tests.py`.

**Conventions:**
- New exceptions inherit from existing `ShortenerError` in `shortener/exceptions.py` (do NOT rename the base — minimizes churn).
- New code in Traditional Chinese docstrings where the surrounding code already uses Chinese.
- `black .` + `ruff check .` before each commit.

---

## Phase 0 — Dependency & Facebook Removal

Keep it small and get it out of the way before touching the data model.

### Task 0.1 — Install `django-ratelimit`

**Goal:** Make the rate-limit decorator available.

**Do:**
```bash
uv add django-ratelimit
```

**Check:** `pyproject.toml` gains the dependency; `uv.lock` updates. Import works in `python manage.py shell`:
```python
from django_ratelimit.decorators import ratelimit
```

**Checkpoint:** commit `chore: add django-ratelimit`.

---

### Task 0.2 — Remove Facebook OAuth

**Goal:** Drop Facebook from code, config, templates, and docs. Google-only going forward.

**Files to change:**
- `core/settings.py` — delete `allauth.socialaccount.providers.facebook` from `INSTALLED_APPS`; delete the `"facebook"` block inside `SOCIALACCOUNT_PROVIDERS`.
- `.env.example` — delete `FACEBOOK_CLIENT_ID` and `FACEBOOK_SECRET_KEY` lines.
- `templates/` — grep for `facebook` (case-insensitive) and remove all matches: login button partial, icon references, provider display text branches.
- `templates/socialaccount/` — if any Facebook-specific override exists, delete it.
- `README.md` — remove the Facebook setup section; rewrite OAuth section as Google-only.
- `doc/url_shortener_spec.md`, `doc/development_roadmap.md` — append a one-line note "Facebook login removed 2026-04-21" at the OAuth section.

**Find Facebook references:**
```bash
grep -ri "facebook" --include="*.py" --include="*.html" --include="*.md" --include=".env*"
```

**Test:**
- Run `python manage.py check` — no errors.
- Start `python manage.py runserver`, open `/`, confirm only Google button appears (after we do template edits in Phase 4 this will render the new design; for now just verify no crash).
- Run `python manage.py test` — existing tests still pass.

**Manual cleanup (do it later, not part of commit):** from Django admin delete the Facebook `SocialApp` row if one exists. Data not schema, no migration.

**Checkpoint:** commit `refactor: remove Facebook OAuth`.

---

## Phase 1 — Data Foundation

Build the data model and migrations in one coherent batch. Once migrations are applied, every later task has the columns it needs.

### Task 1.1 — Create `users` app

**Goal:** Scaffold the rebuilt `users` app.

**Do:**
```bash
python manage.py startapp users
```

**Files to edit:**
- `users/apps.py` — rename `name = "users"` (should be auto) and add a `ready()` hook that imports signals (placeholder for Task 1.2):
  ```python
  class UsersConfig(AppConfig):
      default_auto_field = "django.db.models.BigAutoField"
      name = "users"

      def ready(self):
          from . import signals  # noqa: F401
  ```
- `core/settings.py` — add `"users"` to `INSTALLED_APPS` (put it AFTER the allauth entries so its signals register after Django's built-in User is ready).
- `users/__init__.py` — leave empty.

**Check:** `python manage.py check` passes.

**Checkpoint:** not yet — we'll commit when the model is in place in the next task.

---

### Task 1.2 — `UserProfile` model + auto-create signal

**Goal:** Every `User` automatically has a `UserProfile`. Guests will later set `is_guest=True` and `expires_at`.

**Files:**
- `users/models.py`:
  ```python
  from django.conf import settings
  from django.db import models


  class UserProfile(models.Model):
      user = models.OneToOneField(
          settings.AUTH_USER_MODEL,
          on_delete=models.CASCADE,
          related_name="profile",
      )
      is_guest = models.BooleanField(default=False)
      is_banned = models.BooleanField(default=False)
      expires_at = models.DateTimeField(null=True, blank=True)
      created_at = models.DateTimeField(auto_now_add=True)

      def __str__(self):
          role = "guest" if self.is_guest else ("banned" if self.is_banned else "user")
          return f"{self.user.username} ({role})"
  ```
- `users/signals.py`:
  ```python
  from django.conf import settings
  from django.db.models.signals import post_save
  from django.dispatch import receiver

  from .models import UserProfile


  @receiver(post_save, sender=settings.AUTH_USER_MODEL)
  def create_profile(sender, instance, created, **kwargs):
      if created:
          UserProfile.objects.create(user=instance)
  ```
- `users/admin.py` — register `UserProfile` so you can see/unban via admin:
  ```python
  from django.contrib import admin

  from .models import UserProfile


  @admin.register(UserProfile)
  class UserProfileAdmin(admin.ModelAdmin):
      list_display = ("user", "is_guest", "is_banned", "expires_at", "created_at")
      list_filter = ("is_guest", "is_banned")
      search_fields = ("user__username",)
  ```

**Migration:**
```bash
python manage.py makemigrations users
```
> 舊資料不保留，不做 data migration!

The generated `0001_initial.py` only creates the schema. Add a **data migration** to backfill profiles for pre-existing users:

```bash
python manage.py makemigrations users --empty --name backfill_profiles
```

Edit the new migration:
```python
from django.db import migrations


def backfill(apps, schema_editor):
    User = apps.get_model("auth", "User")
    UserProfile = apps.get_model("users", "UserProfile")
    for user in User.objects.all():
        UserProfile.objects.get_or_create(user=user)


class Migration(migrations.Migration):
    dependencies = [("users", "0001_initial")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
```

**Apply + verify:**
```bash
python manage.py migrate
python manage.py shell -c "from django.contrib.auth.models import User; print([(u.username, u.profile.is_guest) for u in User.objects.all()])"
```

**Test (`users/tests.py`):**
- `test_profile_auto_created_on_user_create` — `User.objects.create_user(...)` then `assertTrue(user.profile)` and `is_guest=False, is_banned=False, expires_at is None`.
- `test_backfill` — not needed as unit test; the data migration is one-shot.

Run: `python manage.py test users`.

**Checkpoint:** commit `feat(users): add UserProfile model with auto-create signal`.

---

### Task 1.3 — Add `expires_at` to `URLModel`

**Goal:** Every URL now carries its own expiry timestamp (nullable = permanent).

**Files:**
- `shortener/models.py` — add inside `URLModel`:
  ```python
  expires_at = models.DateTimeField(
      null=True, blank=True, db_index=True, verbose_name="到期時間"
  )
  ```

**Migration:**
```bash
python manage.py makemigrations shortener
python manage.py migrate
```

Existing rows get `expires_at=NULL` (permanent) — that's the admin semantic, which is fine as a backfill default.

**Test:** add one sanity test in `shortener/tests.py`:
```python
def test_urlmodel_expires_at_nullable(self):
    url = URLModel.objects.create(user=self.user1, original_url="https://x.com", short_code="abc123")
    self.assertIsNone(url.expires_at)
```

**Checkpoint:** commit `feat(shortener): add URLModel.expires_at`.

---

### Task 1.4 — `RateLimitEvent` model

**Goal:** Persist each rate-limit breach so we can count them across a rolling window.

**Files:**
- `shortener/models.py` — new class:
  ```python
  class RateLimitEvent(models.Model):
      user = models.ForeignKey(
          User,
          on_delete=models.CASCADE,
          related_name="rate_limit_events",
          verbose_name="使用者",
      )
      created_at = models.DateTimeField(auto_now_add=True, db_index=True)

      class Meta:
          verbose_name = "Rate Limit Event"
          verbose_name_plural = "Rate Limit Events"
          ordering = ["-created_at"]

      def __str__(self):
          return f"{self.user.username} @ {self.created_at:%Y-%m-%d %H:%M:%S}"
  ```
- `shortener/admin.py` — register it (read-only) for observability:
  ```python
  @admin.register(RateLimitEvent)
  class RateLimitEventAdmin(admin.ModelAdmin):
      list_display = ("user", "created_at")
      list_filter = ("created_at",)
      search_fields = ("user__username",)
      readonly_fields = ("user", "created_at")
  ```

**Migration + test:**
```bash
python manage.py makemigrations shortener
python manage.py migrate
```

No dedicated test here — the model is trivial; it'll be exercised via `RateLimitService` tests later.

**Checkpoint:** commit `feat(shortener): add RateLimitEvent model`.

---

## Phase 2 — Domain Services

Now the policy layer. Each service has a focused job. Build bottom-up (fewest deps first): exceptions → blocklist → user → rate limit → url (updates).

### Task 2.1 — Add domain exceptions

**Goal:** Named exceptions for every business-rule failure.

**Files (`shortener/exceptions.py`):** append to existing file, do NOT rename `ShortenerError`:
```python
class UrlExpiredError(ShortenerError):
    """短網址已過期"""
    pass


class BlockedDomainError(ShortenerError):
    """目標網域在黑名單上"""
    pass


class QuotaExceededError(ShortenerError):
    """已達該使用者的 URL 配額上限"""
    pass


class UserBannedError(ShortenerError):
    """使用者已被停權"""
    pass
```

**Test:** not needed — exceptions are trivial. They'll be covered via service tests that assert `with self.assertRaises(...)`.

**Checkpoint:** commit `feat(shortener): add domain exceptions for expiry, blocklist, quota, ban`.

---

### Task 2.2 — `BlocklistService` + seed blocklist file

**Goal:** Block known-bad domains at URL creation. Small, fast, local.

**Files:**
- `shortener/data/blocklist.txt` (create directory and file):
  ```
  # Abuse-prone shortener services (prevent shortener-nesting)
  bit.ly
  t.co
  tinyurl.com
  goo.gl
  ow.ly
  is.gd
  buff.ly

  # Known phishing-prone placeholders; expand as needed
  ```
- `shortener/services.py` — add new class (keep near the top, below `sqids` init):
  ```python
  from functools import lru_cache
  from pathlib import Path
  from urllib.parse import urlparse

  BLOCKLIST_FILE = Path(__file__).resolve().parent / "data" / "blocklist.txt"


  class BlocklistService:
      """本地 domain 黑名單"""

      @staticmethod
      @lru_cache(maxsize=1)
      def _load() -> frozenset[str]:
          lines = BLOCKLIST_FILE.read_text(encoding="utf-8").splitlines()
          return frozenset(
              line.strip().lower()
              for line in lines
              if line.strip() and not line.startswith("#")
          )

      @staticmethod
      def is_blocked(url: str) -> bool:
          host = urlparse(url).hostname or ""
          host = host.lower().removeprefix("www.")
          return host in BlocklistService._load()
  ```

**Why `lru_cache`?** Blocklist is a small file, loaded once per process — avoid re-reading on every request.

**Tests (`shortener/tests.py`):**
```python
class BlocklistServiceTestCase(TestCase):
    def test_blocked_domain(self):
        self.assertTrue(BlocklistService.is_blocked("https://bit.ly/abc"))

    def test_clean_domain(self):
        self.assertFalse(BlocklistService.is_blocked("https://example.com/x"))

    def test_strips_www_prefix(self):
        self.assertTrue(BlocklistService.is_blocked("https://www.bit.ly/abc"))

    def test_case_insensitive(self):
        self.assertTrue(BlocklistService.is_blocked("https://BIT.LY/abc"))

    def test_partial_match_not_blocked(self):
        # "notbit.ly" must not be matched as "bit.ly"
        self.assertFalse(BlocklistService.is_blocked("https://notbit.ly/x"))
```

Run: `python manage.py test shortener.tests.BlocklistServiceTestCase`.

**Checkpoint:** commit `feat(shortener): add BlocklistService with local domain blocklist`.

---

### Task 2.3 — `UserService`

**Goal:** Centralise identity-derived policy (guest creation, quota, lifetime, ban).

**Files (`users/services.py`):** new file.
```python
"""
User-related services: guest provisioning, quotas, URL lifetimes, banning.
"""
import secrets
from datetime import timedelta

from django.contrib.auth import logout
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.http import HttpRequest
from django.utils import timezone

GUEST_QUOTA = 5
GOOGLE_QUOTA = 10
GUEST_LIFETIME = timedelta(hours=24)
GOOGLE_URL_LIFETIME = timedelta(days=7)


class UserService:

    @staticmethod
    def create_guest_user() -> User:
        """建立訪客帳號，自動產生 username 並設定 24h 過期。"""
        for _ in range(3):  # retry on the extremely unlikely collision
            username = f"guest_{secrets.token_hex(4)}"
            try:
                with transaction.atomic():
                    user = User.objects.create(username=username, email="")
                    user.set_unusable_password()
                    user.save()
                    profile = user.profile  # auto-created via signal
                    profile.is_guest = True
                    profile.expires_at = timezone.now() + GUEST_LIFETIME
                    profile.save()
                    return user
            except IntegrityError:
                continue
        raise RuntimeError("Failed to allocate a unique guest username after 3 tries")

    @staticmethod
    def get_quota(user: User) -> int | float:
        if user.is_staff:
            return float("inf")
        if user.profile.is_guest:
            return GUEST_QUOTA
        return GOOGLE_QUOTA

    @staticmethod
    def get_url_lifetime(user: User) -> timedelta | None:
        if user.is_staff:
            return None
        if user.profile.is_guest:
            # Align URL expiry with the guest account's own expiry.
            return user.profile.expires_at - timezone.now()
        return GOOGLE_URL_LIFETIME

    @staticmethod
    def ban_user(user: User, request: HttpRequest | None = None) -> None:
        user.profile.is_banned = True
        user.profile.save(update_fields=["is_banned"])
        if request is not None:
            logout(request)
```

**Tests (`users/tests.py`):** append to the file from Task 1.2:
```python
import re
from datetime import timedelta
from django.contrib.auth.models import User
from django.test import TestCase, RequestFactory
from django.utils import timezone

from .services import UserService, GUEST_QUOTA, GOOGLE_QUOTA, GOOGLE_URL_LIFETIME


class UserServiceTestCase(TestCase):
    def test_create_guest_user(self):
        user = UserService.create_guest_user()
        self.assertTrue(re.match(r"^guest_[0-9a-f]{8}$", user.username))
        self.assertTrue(user.profile.is_guest)
        self.assertFalse(user.has_usable_password())
        # expires_at ≈ now + 24h (allow 1-minute drift)
        drift = abs((user.profile.expires_at - timezone.now()) - timedelta(hours=24))
        self.assertLess(drift.total_seconds(), 60)

    def test_get_quota(self):
        guest = UserService.create_guest_user()
        regular = User.objects.create_user(username="alice")
        admin = User.objects.create_user(username="admin", is_staff=True)
        self.assertEqual(UserService.get_quota(guest), GUEST_QUOTA)
        self.assertEqual(UserService.get_quota(regular), GOOGLE_QUOTA)
        self.assertEqual(UserService.get_quota(admin), float("inf"))

    def test_get_url_lifetime(self):
        guest = UserService.create_guest_user()
        regular = User.objects.create_user(username="alice")
        admin = User.objects.create_user(username="admin", is_staff=True)
        # Guest lifetime is a bit less than 24h (time has passed since creation)
        self.assertLess(UserService.get_url_lifetime(guest), timedelta(hours=24))
        self.assertGreater(UserService.get_url_lifetime(guest), timedelta(hours=23, minutes=59))
        self.assertEqual(UserService.get_url_lifetime(regular), GOOGLE_URL_LIFETIME)
        self.assertIsNone(UserService.get_url_lifetime(admin))

    def test_ban_user(self):
        user = User.objects.create_user(username="x")
        UserService.ban_user(user)
        user.refresh_from_db()
        self.assertTrue(user.profile.is_banned)
```

Run: `python manage.py test users`.

**Checkpoint:** commit `feat(users): add UserService (guest creation, quota, lifetime, ban)`.

---

### Task 2.4 — `RateLimitService`

**Goal:** Record rate-limit breaches and auto-ban after 5 in 10 minutes.

**Files (`shortener/services.py`):** append at bottom.
```python
from datetime import timedelta
from django.utils import timezone

from users.services import UserService
from .models import RateLimitEvent

BAN_THRESHOLD = 5
BAN_WINDOW = timedelta(minutes=10)


class RateLimitService:

    @staticmethod
    def register_hit(user, request=None) -> None:
        """寫入一次 rate-limit 觸發事件；若 10 分鐘內達門檻則 ban。"""
        RateLimitEvent.objects.create(user=user)
        window_start = timezone.now() - BAN_WINDOW
        recent = RateLimitEvent.objects.filter(
            user=user, created_at__gte=window_start
        ).count()
        if recent >= BAN_THRESHOLD:
            UserService.ban_user(user, request)
```

**Tests (`shortener/tests.py`):**
```python
from datetime import timedelta
from django.utils import timezone
from shortener.services import RateLimitService, BAN_THRESHOLD
from shortener.models import RateLimitEvent


class RateLimitServiceTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="rl-user")

    def test_threshold_triggers_ban(self):
        for _ in range(BAN_THRESHOLD):
            RateLimitService.register_hit(self.user)
        self.user.refresh_from_db()
        self.assertTrue(self.user.profile.is_banned)

    def test_below_threshold_no_ban(self):
        for _ in range(BAN_THRESHOLD - 1):
            RateLimitService.register_hit(self.user)
        self.user.refresh_from_db()
        self.assertFalse(self.user.profile.is_banned)

    def test_old_events_dont_count(self):
        # Seed old events outside window; they must not trigger ban.
        old_time = timezone.now() - timedelta(minutes=30)
        for _ in range(BAN_THRESHOLD):
            event = RateLimitEvent.objects.create(user=self.user)
            RateLimitEvent.objects.filter(pk=event.pk).update(created_at=old_time)
        # One fresh hit should NOT trip the ban alone.
        RateLimitService.register_hit(self.user)
        self.user.refresh_from_db()
        self.assertFalse(self.user.profile.is_banned)
```

Run: `python manage.py test shortener.tests.RateLimitServiceTestCase`.

**Checkpoint:** commit `feat(shortener): add RateLimitService with auto-ban at 5 hits/10min`.

---

### Task 2.5 — Extend `URLService` (policy checks + expiry)

**Goal:** Wire ban / blocklist / quota / lifetime into creation; detect expired URLs in lookup.

**Files (`shortener/services.py`):** modify `URLService.get_or_create_short_url` and `URLService.get_url_by_code`.

**`get_or_create_short_url`** — insert new checks before any DB write, and stamp `expires_at` on create. Logic order:
```python
@staticmethod
def get_or_create_short_url(user, original_url):
    # 1. URL format (existing)
    validator = URLValidator()
    try:
        validator(original_url)
    except ValidationError:
        raise ValidationError("Invalid URL format") from None

    # 2. Ban
    if user.profile.is_banned:
        raise UserBannedError("User is banned")

    # 3. Blocklist
    if BlocklistService.is_blocked(original_url):
        raise BlockedDomainError("此網域不允許縮短")

    # 4. Dedup (existing behaviour — before quota, since returning an existing URL shouldn't count as "creating")
    existing = URLModel.objects.filter(user=user, original_url=original_url).first()
    if existing:
        return (existing, False)

    # 5. Active quota
    now = timezone.now()
    active_count = URLModel.objects.filter(user=user).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now)
    ).count()
    quota = UserService.get_quota(user)
    if active_count >= quota:
        raise QuotaExceededError(f"已達配額上限（{quota} 個）")

    # 6. Lifetime → expires_at
    lifetime = UserService.get_url_lifetime(user)
    expires_at = None if lifetime is None else now + lifetime

    # 7. Create + Sqids encode (keep existing two-step approach)
    url_obj = URLModel.objects.create(
        user=user, original_url=original_url, short_code="", expires_at=expires_at
    )
    url_obj.short_code = sqids.encode([user.id, url_obj.id])
    url_obj.save()
    return (url_obj, True)
```

Add imports at top of `services.py`:
```python
from django.db.models import Q
from django.utils import timezone
from users.services import UserService
from .exceptions import (
    BlockedDomainError,
    QuotaExceededError,
    UrlExpiredError,
    UserBannedError,
)
```

**`get_url_by_code`** — raise `UrlExpiredError` when past expiry:
```python
@staticmethod
def get_url_by_code(code: str, check_active: bool = True) -> URLModel:
    try:
        decoded = sqids.decode(code)
        if len(decoded) != 2:
            raise UrlNotFoundError(f"Invalid short code: {code}")
        user_id, url_id = decoded
        url_obj = URLModel.objects.get(id=url_id, user_id=user_id)
    except (ValueError, URLModel.DoesNotExist):
        raise UrlNotFoundError(f"URL not found: {code}") from None

    if check_active and not url_obj.is_active:
        raise UrlNotFoundError(f"URL is inactive: {code}")

    if url_obj.expires_at is not None and url_obj.expires_at < timezone.now():
        raise UrlExpiredError(f"URL expired: {code}")

    return url_obj
```

**Note on existing `create_short_url`:** it's still used by existing tests and is called from `get_or_create_short_url` in the old flow. We're folding its logic into the new `get_or_create_short_url` directly (steps 6–7 above), but the standalone `create_short_url` is kept unchanged so existing tests still pass. It doesn't enforce policy because it's no longer the primary creation path; callers should use `get_or_create_short_url`.

**Tests (`shortener/tests.py`):** add a dedicated class with coverage for each policy branch. Minimum cases:
```python
from datetime import timedelta
from django.utils import timezone
from shortener.exceptions import (
    BlockedDomainError, QuotaExceededError, UrlExpiredError, UserBannedError
)
from users.services import UserService


class URLServicePolicyTestCase(TestCase):
    def setUp(self):
        self.guest = UserService.create_guest_user()
        self.regular = User.objects.create_user(username="alice")
        self.admin = User.objects.create_user(username="admin", is_staff=True)

    def test_guest_url_expires_with_guest(self):
        url, _ = URLService.get_or_create_short_url(self.guest, "https://example.com")
        self.assertEqual(url.expires_at, self.guest.profile.expires_at)

    def test_google_url_expires_in_7d(self):
        url, _ = URLService.get_or_create_short_url(self.regular, "https://example.com")
        drift = abs((url.expires_at - timezone.now()) - timedelta(days=7))
        self.assertLess(drift.total_seconds(), 60)

    def test_admin_url_permanent(self):
        url, _ = URLService.get_or_create_short_url(self.admin, "https://example.com")
        self.assertIsNone(url.expires_at)

    def test_blocklist_raises(self):
        with self.assertRaises(BlockedDomainError):
            URLService.get_or_create_short_url(self.regular, "https://bit.ly/abc")

    def test_banned_user_raises(self):
        self.regular.profile.is_banned = True
        self.regular.profile.save()
        with self.assertRaises(UserBannedError):
            URLService.get_or_create_short_url(self.regular, "https://example.com")

    def test_quota_exceeded(self):
        for i in range(5):  # guest quota = 5
            URLService.get_or_create_short_url(self.guest, f"https://a{i}.com")
        with self.assertRaises(QuotaExceededError):
            URLService.get_or_create_short_url(self.guest, "https://new.com")

    def test_expired_urls_dont_count_toward_quota(self):
        # Fill quota with URLs that are already expired.
        past = timezone.now() - timedelta(hours=1)
        for i in range(5):
            url, _ = URLService.get_or_create_short_url(self.guest, f"https://a{i}.com")
            URLModel.objects.filter(pk=url.pk).update(expires_at=past)
        # A new creation should succeed because no URLs are ACTIVE.
        url, _ = URLService.get_or_create_short_url(self.guest, "https://new.com")
        self.assertIsNotNone(url)

    def test_get_url_by_code_expired(self):
        url, _ = URLService.get_or_create_short_url(self.guest, "https://example.com")
        URLModel.objects.filter(pk=url.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        with self.assertRaises(UrlExpiredError):
            URLService.get_url_by_code(url.short_code)
```

Run: `python manage.py test shortener.tests.URLServicePolicyTestCase`.

**Checkpoint:** commit `feat(shortener): enforce ban/blocklist/quota/expiry in URLService`.

---

## Phase 3 — Views & URL Routing

### Task 3.1 — Guest login view

**Goal:** A public POST endpoint that provisions a guest user and logs them in; IP rate-limited.

**Files:**
- `users/views.py` — new file:
  ```python
  from django.contrib.auth import login
  from django.http import HttpRequest, HttpResponse
  from django.shortcuts import redirect, render
  from django.views.decorators.http import require_POST
  from django_ratelimit.decorators import ratelimit
  from django_ratelimit.exceptions import Ratelimited

  from .services import UserService


  @require_POST
  @ratelimit(key="ip", rate="1/h", block=False)
  def guest_login_view(request: HttpRequest) -> HttpResponse:
      if getattr(request, "limited", False):
          return render(request, "shortener/rate_limited.html", status=429)
      user = UserService.create_guest_user()
      login(request, user)
      return redirect("my_urls")
  ```

  **Why `block=False`?** Easier to render our own 429 template than let the library raise. Check `request.limited` manually.

- `users/urls.py` — new file:
  ```python
  from django.urls import path

  from . import views

  urlpatterns = [
      path("guest-login/", views.guest_login_view, name="guest_login"),
  ]
  ```

- `core/urls.py` — include before allauth so allauth's catch-all under `/accounts/` doesn't steal it. New ordering:
  ```python
  urlpatterns = [
      path("admin/", admin.site.urls),
      path("accounts/", include("users.urls")),      # guest login lives at /accounts/guest-login/
      path("accounts/", include("allauth.urls")),     # Google OAuth flows
      path("", include("shortener.urls")),
  ]
  ```
  Django resolves paths in order; listing `users.urls` first lets it match `/accounts/guest-login/` before allauth tries.

**Tests (`users/tests.py`):**
```python
from django.test import Client
from django.urls import reverse


class GuestLoginViewTestCase(TestCase):
    def setUp(self):
        self.client = Client()

    def test_post_creates_guest_and_logs_in(self):
        resp = self.client.post("/accounts/guest-login/")
        self.assertRedirects(resp, "/my-urls/")
        # Session now has a guest user
        user = resp.wsgi_request.user  # after redirect, the new request's user won't be set; check via session
        self.assertIn("_auth_user_id", self.client.session)

    def test_get_is_method_not_allowed(self):
        resp = self.client.get("/accounts/guest-login/")
        self.assertEqual(resp.status_code, 405)
```

**Manual check:** start runserver, `curl -X POST http://127.0.0.1:8000/accounts/guest-login/ --cookie-jar jar.txt -L` → ends up at `/my-urls/`.

**Checkpoint:** commit `feat(users): add guest login view with IP rate limit`.

---

### Task 3.2 — Update `my_urls_view` (shorten flow)

**Goal:** Enforce rate limit on URL creation, handle all new exceptions, expose quota info to template.

**Files (`shortener/views.py`):**

Add imports:
```python
from django_ratelimit.decorators import ratelimit
from django.db.models import Q
from django.utils import timezone

from .exceptions import (
    BlockedDomainError,
    QuotaExceededError,
    UserBannedError,
)
from users.services import UserService
from .services import RateLimitService
```

Split the POST path out of `my_urls_view` into a dedicated `shorten_view` so the decorator only applies to creation. Rename/refactor:

```python
@login_required
@ratelimit(key="user", rate="5/m", block=False)
def shorten_view(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return redirect("my_urls")

    if getattr(request, "limited", False):
        RateLimitService.register_hit(request.user, request)
        # After register_hit the user might now be banned; either way show 429
        return render(request, "shortener/rate_limited.html", status=429)

    original_url = request.POST.get("original_url", "").strip()
    if not original_url:
        messages.error(request, "Please enter a URL")
        return redirect("my_urls")

    try:
        url_obj, created = URLService.get_or_create_short_url(request.user, original_url)
        short_url = f"{request.build_absolute_uri('/')}{url_obj.short_code}/"
        msg = f"Short URL created: {short_url}" if created else f"You've already shortened this URL: {short_url}"
        (messages.success if created else messages.warning)(request, msg)
    except ValidationError as e:
        messages.error(request, str(e))
    except BlockedDomainError:
        messages.error(request, "此網域不允許縮短")
    except QuotaExceededError as e:
        messages.error(request, str(e))
    except UserBannedError:
        from django.contrib.auth import logout as auth_logout
        auth_logout(request)
        return render(request, "users/banned.html", status=403)

    return redirect("my_urls")
```

Then reduce `my_urls_view` to GET-only (remove its POST branch):
```python
@login_required
def my_urls_view(request: HttpRequest) -> HttpResponse:
    status = request.GET.get("status", "all")
    sort_by = request.GET.get("sort_by", "created_at")
    order = request.GET.get("order", "desc")

    urls = URLService.get_filtered_urls_with_stats(
        user=request.user,
        status_filter=status if status != "all" else None,
        sort_by=sort_by,
        sort_order=order,
    )

    now = timezone.now()
    active_count = URLModel.objects.filter(user=request.user).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now)
    ).count()
    quota = UserService.get_quota(request.user)

    context = {
        "urls": urls,
        "current_status": status,
        "current_sort_by": sort_by,
        "current_order": order,
        "active_count": active_count,
        "quota": quota,
        "quota_is_unlimited": quota == float("inf"),
        "url_lifetime": UserService.get_url_lifetime(request.user),
        # 改成 expires_at
    }
    return render(request, "shortener/my_urls.html", context)
```

`quota_is_unlimited` exists so the template can render "∞" instead of `inf`.

**URL routing (`shortener/urls.py`):**
```python
urlpatterns = [
    path("", views.home_view, name="home"),
    path("ping/", views.health_check, name="ping"),
    path("my-urls/", views.my_urls_view, name="my_urls"),
    path("shorten/", views.shorten_view, name="shorten"),   # NEW — dedicated POST endpoint
    path("my-urls/toggle/<int:url_id>/", views.toggle_url_view, name="toggle_url"),
    path("stats/<str:code>/", views.url_stats_view, name="url_stats"),
    path("<str:code>/", views.redirect_view, name="redirect"),
]
```

Template form action changes in Phase 4 to point at `{% url 'shorten' %}` instead of `{% url 'my_urls' %}`.

**Tests (`shortener/tests.py`):** one focused view test per exception path — use `Client` with `login`:
```python
class ShortenViewTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="pw")
        self.client = Client()
        self.client.login(username="alice", password="pw")

    def test_blocked_domain_shows_error(self):
        resp = self.client.post("/shorten/", {"original_url": "https://bit.ly/x"}, follow=True)
        self.assertContains(resp, "不允許")

    def test_banned_user_gets_403(self):
        self.user.profile.is_banned = True
        self.user.profile.save()
        resp = self.client.post("/shorten/", {"original_url": "https://ok.com"})
        self.assertEqual(resp.status_code, 403)
```

Rate-limit view testing is tricky (Django test client shares cache across requests) — skip it at the view layer; `RateLimitService` is already unit-tested.

**Checkpoint:** commit `feat(shortener): extract shorten view, wire rate limit + policy exceptions`.

---

### Task 3.3 — Update `redirect_view` for expired URLs

**Goal:** Expired links render a dedicated page instead of 404; no click is recorded.

**Files (`shortener/views.py`):**
```python
from .exceptions import UrlExpiredError  # add import

def redirect_view(request: HttpRequest, code: str) -> HttpResponse:
    try:
        url_obj = URLService.get_url_by_code(code)
    except UrlNotFoundError:
        return render(request, "shortener/404.html", status=404)
    except UrlExpiredError:
        return render(request, "shortener/expired.html", status=200)

    AnalyticsService.record_click(url_obj, request)
    return redirect(url_obj.original_url)
```

**Tests (`shortener/tests.py`):**
```python
def test_expired_url_shows_expired_page_no_click(self):
    user = User.objects.create_user(username="u")
    url = URLModel.objects.create(
        user=user,
        original_url="https://example.com",
        short_code="abc123",
        expires_at=timezone.now() - timedelta(hours=1),
    )
    # Must use the real sqids short_code — create via service instead:
    from shortener.services import URLService
    url2, _ = URLService.get_or_create_short_url(user, "https://another.com")
    URLModel.objects.filter(pk=url2.pk).update(
        expires_at=timezone.now() - timedelta(hours=1)
    )
    resp = self.client.get(f"/{url2.short_code}/")
    self.assertEqual(resp.status_code, 200)
    self.assertTemplateUsed(resp, "shortener/expired.html")
    self.assertEqual(ClickLog.objects.filter(url=url2).count(), 0)
```

**Checkpoint:** commit `feat(shortener): render expired page instead of redirecting past-expiry links`.

---

## Phase 4 — Templates

Do these after views compile so you can render and eyeball them live.

### Task 4.1 — Homepage with two login buttons

**Goal:** Unauth users see both **Login with Google** and **Try as Guest**.

**Files (`shortener/templates/shortener/home.html`):** rewrite content block. Essentials:
```html
{% extends "base.html" %}
{% load socialaccount %}

{% block content %}
<section class="hero">
  <h2>Shorten URLs. Track clicks.</h2>
  <p>Try it instantly — no signup required.</p>

  <form method="post" action="{% url 'guest_login' %}" class="guest-form">
    {% csrf_token %}
    <button type="submit" class="btn btn-primary">Try as Guest (24h)</button>
  </form>

  <a href="{% provider_login_url 'google' %}" class="btn btn-secondary">Login with Google</a>

  <p class="fine-print">
    Guest accounts and their links are deleted 24 hours after creation.
    Google-logged-in users' links expire after 7 days.
  </p>
</section>
{% endblock %}
```

**Why a form for guest login?** POST + CSRF — prevents CSRF-less bot spam and aligns with the rate-limited endpoint.

Remove any existing Facebook button block.

**Test:** eye-test via runserver at `/`. No unit test needed beyond the view test already in place.

**Checkpoint:** commit `feat(templates): new homepage with Google + Guest login`.

---

### Task 4.2 — Navbar guest info + Facebook removal

**Goal:** Guests see `Guest • expires <time>` in the navbar. All Facebook mentions gone.

**Files (`templates/base.html`):** in the authenticated block, split by identity:
```html
{% if user.is_authenticated %}
<div class="user-info">
  {% if user.profile.is_guest %}
    <span title="Your account and URLs will be deleted at expiry">
      Guest • expires {{ user.profile.expires_at|date:"Y-m-d H:i" }}
    </span>
  {% else %}
    <span>
      {{ user.email|default:user.username }}{% for account in user.socialaccount_set.all %} ({{ account.provider|title }}){% endfor %}
    </span>
  {% endif %}
  <a href="{% url 'my_urls' %}" class="btn btn-secondary">My URLs</a>
  <form method="post" action="{% url 'account_logout' %}" class="logout-form">
    {% csrf_token %}
    <button type="submit" class="btn btn-secondary">Logout</button>
  </form>
</div>
{% endif %}
```

Since Google is the only social provider now, the `for account in user.socialaccount_set.all` loop will never include Facebook — no extra filtering needed.

**Also check:** `templates/socialaccount/` — if any file references `facebook` specifically, delete it. Allauth falls back to its default templates.

**Checkpoint:** commit `feat(templates): show guest expiry in navbar; drop Facebook mentions`.

---

### Task 4.3 — `/my-urls/` quota + expires_at column

**Goal:** Show active quota status, expiry per URL, and identity-specific form help text.

**Files (`shortener/templates/shortener/my_urls.html`):** changes are additive. Key pieces:

Near the form:
```html
<p class="quota-status">
  {% if quota_is_unlimited %}
    Active URLs: {{ active_count }} (unlimited)
  {% else %}
    Active URLs: {{ active_count }} / {{ quota }}
  {% endif %}
</p>
<p class="form-help">
  {% if user.profile.is_guest %}
    Your links will expire at {{ user.profile.expires_at|date:"Y-m-d H:i" }} (when your guest account is deleted).
  {% elif user.is_staff %}
    {# no help text for admin #}
  {% else %}
    Links expire 7 days after creation.
  {% endif %}
</p>
```

Change the form `action` attribute to `{% url 'shorten' %}` (pointing at the new dedicated endpoint from Task 3.2).

In the URL list, add a column for `expires_at`:
```html
<td>
  {% if url.expires_at %}
    {{ url.expires_at|date:"Y-m-d H:i" }}
  {% else %}
    Permanent
  {% endif %}
</td>
```

(Add matching `<th>` in the header row.)

**Test:** runserver, log in with Google account, verify list renders; create a URL; verify expiry shows 7 days out.

**Checkpoint:** commit `feat(templates): show quota + expiry on /my-urls/`.

---

### Task 4.4 — New static templates (expired / rate_limited / banned)

**Goal:** Simple shells — no branching logic.

**Files:**
- `shortener/templates/shortener/expired.html`:
  ```html
  {% extends "base.html" %}
  {% block title %}Link expired{% endblock %}
  {% block content %}
  <section class="message-page">
    <h2>This link has expired.</h2>
    <p>The short URL you followed is no longer active.</p>
  </section>
  {% endblock %}
  ```
- `shortener/templates/shortener/rate_limited.html`:
  ```html
  {% extends "base.html" %}
  {% block title %}Too many requests{% endblock %}
  {% block content %}
  <section class="message-page">
    <h2>Too many requests</h2>
    <p>Please try again in a few minutes.</p>
  </section>
  {% endblock %}
  ```
- `users/templates/users/banned.html`:
  ```html
  {% extends "base.html" %}
  {% block title %}Account suspended{% endblock %}
  {% block content %}
  <section class="message-page">
    <h2>Account suspended</h2>
    <p>This account has been suspended due to repeated policy violations.</p>
  </section>
  {% endblock %}
  ```

**Note:** `users/templates/users/` directory needs to be created. `TEMPLATES.APP_DIRS = True` in settings already tells Django to find per-app template dirs — no extra config.

**Checkpoint:** commit `feat(templates): add expired, rate_limited, banned templates`.

---

## Phase 5 — Cleanup Management Commands

### Task 5.1 — `cleanup_expired_urls`

**Goal:** Delete any URL past its `expires_at` (admin/null rows untouched). Idempotent.

**Files:**
- `shortener/management/__init__.py` — empty file.
- `shortener/management/commands/__init__.py` — empty file.
- `shortener/management/commands/cleanup_expired_urls.py`:
  ```python
  from django.core.management.base import BaseCommand
  from django.utils import timezone

  from shortener.models import URLModel


  class Command(BaseCommand):
      help = "Delete URLs whose expires_at is in the past (cascades ClickLogs)."

      def handle(self, *args, **options):
          deleted, _ = URLModel.objects.filter(
              expires_at__lt=timezone.now()
          ).delete()
          self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} expired URLs"))
  ```

**Test (`shortener/tests.py`):**
```python
from io import StringIO
from django.core.management import call_command


class CleanupExpiredUrlsTestCase(TestCase):
    def test_deletes_only_expired(self):
        user = User.objects.create_user(username="u")
        fresh, _ = URLService.get_or_create_short_url(user, "https://a.com")
        stale, _ = URLService.get_or_create_short_url(user, "https://b.com")
        URLModel.objects.filter(pk=stale.pk).update(
            expires_at=timezone.now() - timedelta(hours=1)
        )
        out = StringIO()
        call_command("cleanup_expired_urls", stdout=out)
        self.assertTrue(URLModel.objects.filter(pk=fresh.pk).exists())
        self.assertFalse(URLModel.objects.filter(pk=stale.pk).exists())
```

Run: `python manage.py cleanup_expired_urls`.

**Checkpoint:** commit `feat(shortener): add cleanup_expired_urls management command`.

---

### Task 5.2 — `cleanup_expired_guests`

**Goal:** Delete expired guest users. Cascade takes care of their URLs and ClickLogs.

**Files:**
- `users/management/__init__.py` — empty.
- `users/management/commands/__init__.py` — empty.
- `users/management/commands/cleanup_expired_guests.py`:
  ```python
  from django.contrib.auth.models import User
  from django.core.management.base import BaseCommand
  from django.utils import timezone


  class Command(BaseCommand):
      help = "Delete guest users past their expires_at (cascades URLs and ClickLogs)."

      def handle(self, *args, **options):
          qs = User.objects.filter(
              profile__is_guest=True,
              profile__expires_at__lt=timezone.now(),
          )
          count = qs.count()
          qs.delete()
          self.stdout.write(self.style.SUCCESS(f"Deleted {count} expired guest users"))
  ```

**Test (`users/tests.py`):**
```python
class CleanupExpiredGuestsTestCase(TestCase):
    def test_deletes_expired_guest_and_cascades(self):
        from shortener.services import URLService
        from shortener.models import URLModel, ClickLog

        guest = UserService.create_guest_user()
        url, _ = URLService.get_or_create_short_url(guest, "https://x.com")
        ClickLog.objects.create(url=url, ip_address="1.1.1.1")
        # Backdate profile to expired
        guest.profile.expires_at = timezone.now() - timedelta(minutes=1)
        guest.profile.save()

        call_command("cleanup_expired_guests")
        self.assertFalse(User.objects.filter(pk=guest.pk).exists())
        self.assertFalse(URLModel.objects.filter(pk=url.pk).exists())
        self.assertEqual(ClickLog.objects.count(), 0)
```

Run: `python manage.py cleanup_expired_guests`.

**Checkpoint:** commit `feat(users): add cleanup_expired_guests management command`.

---

## Phase 6 — Settings, Admin, Docs

### Task 6.1 — `TIME_ZONE` and final settings pass

**Goal:** Datetimes display in Taipei time; all test/check green.

**Files (`core/settings.py`):**
- Change `TIME_ZONE = "UTC"` → `TIME_ZONE = "Asia/Taipei"`. Leave `USE_TZ = True`.
- Confirm `INSTALLED_APPS` order: `django.contrib.*` → `allauth.*` (without facebook) → `users` → `shortener`.
- Confirm no `django_ratelimit` app registration needed — the package is middleware-free; only its decorator is used.

**Test:** `python manage.py test` should pass end-to-end. Eyeball `/my-urls/` in the browser: expiry times should now show in Taipei.

**Checkpoint:** commit `chore: set TIME_ZONE=Asia/Taipei`.

---

### Task 6.2 — Full test sweep + lint

**Goal:** Green bar before wrapping up.

**Run:**
```bash
python manage.py test
black .
ruff check . --fix
python manage.py check
```

Fix anything that surfaces. If a test relies on UTC output it'll need to be adjusted to use `timezone.now()` comparisons (not hard-coded strings).

**Checkpoint:** commit `chore: formatting + lint fixes` if `black`/`ruff` produced changes.

---

### Task 6.3 — Documentation

**Goal:** README, progress log, roadmap reflect the new behaviour.

**Files:**
- `README.md`:
  - Add "Try as guest" to the feature list.
  - Update the OAuth section to Google-only.
  - Add a "Cleanup" section mentioning the two management commands (note: scheduling comes in Batch 3 / VPS deployment).
- `doc/progress.md` — append an entry for 2026-04-21 summarising Batch 1.
- `doc/url_shortener_spec.md`, `doc/development_roadmap.md` — annotate "Facebook login removed 2026-04-21" at the relevant OAuth section (if not already done in Phase 0).

**Checkpoint:** commit `docs: document guest mode and Facebook removal`.

---

## Final Verification

Run these before declaring done:

1. `python manage.py test` — all green.
2. `python manage.py check` — no warnings.
3. Manual QA loop with runserver:
   - Visit `/`, confirm both login buttons.
   - Click **Try as Guest** → land on `/my-urls/`, navbar shows `Guest • expires <time>`.
   - Create a URL → active quota shows `1/5`.
   - Create 4 more → 6th attempt shows quota error message.
   - Try to shorten `https://bit.ly/abc` → blocklist error.
   - Open short URL → redirects correctly and click recorded (visit `/stats/<code>/`).
   - Log out → re-login with Google → navbar shows provider name, no Facebook.
   - Admin login: verify `UserProfile` and `RateLimitEvent` are manageable from Django admin.
4. Trigger expiry manually: in shell, set a guest URL's `expires_at` to the past, then visit it → `expired.html` renders, no new click.
5. `python manage.py cleanup_expired_urls` and `cleanup_expired_guests` — verify counts.

## Scope Coverage Check

| Spec item | Task(s) |
|---|---|
| Remove Facebook OAuth | 0.2, 4.2 |
| `UserProfile` model + auto-profile signal | 1.1, 1.2 |
| `URLModel.expires_at` | 1.3 |
| `RateLimitEvent` | 1.4 |
| Guest login flow | 2.3 (service), 3.1 (view), 4.1 (template) |
| URL lifetime by identity | 2.3, 2.5 |
| Redirect checks expiry | 2.5, 3.3, 4.4 (expired.html) |
| Local domain blocklist | 2.2 |
| Active URL quota | 2.5, 3.2 (view context), 4.3 (template) |
| Rate limits (URL creation, guest creation) | 3.1, 3.2 |
| Auto-ban at threshold | 2.4 |
| Cleanup commands | 5.1, 5.2 |
| `TIME_ZONE = "Asia/Taipei"` | 6.1 |
| New exceptions | 2.1 |
| Navbar guest info | 4.2 |
| New templates (expired/rate_limited/banned) | 4.4 |
| Docs updates | 6.3 |
