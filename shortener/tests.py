"""
Tests for shortener app
"""

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from .exceptions import AccessDeniedError, UrlNotFoundError
from .models import ClickLog, URLModel
from .services import AnalyticsService, URLService


class URLServiceTestCase(TestCase):
    """URLService 測試"""

    def setUp(self):
        """建立測試資料"""
        self.user1 = User.objects.create_user(username="user1", password="pass123")
        self.user2 = User.objects.create_user(username="user2", password="pass123")

    def test_create_short_url_success(self):
        """測試成功建立短網址"""
        url_obj = URLService.create_short_url(self.user1, "https://www.example.com")

        self.assertIsNotNone(url_obj.id)
        self.assertIsNotNone(url_obj.short_code)
        self.assertEqual(url_obj.original_url, "https://www.example.com")
        self.assertEqual(url_obj.user, self.user1)
        self.assertGreaterEqual(len(url_obj.short_code), 6)  # min_length=6

    def test_create_short_url_invalid_format(self):
        """測試無效的 URL 格式"""
        with self.assertRaises(ValidationError):
            URLService.create_short_url(self.user1, "not-a-valid-url")

        with self.assertRaises(ValidationError):
            URLService.create_short_url(self.user1, "")

    def test_get_url_by_code_success(self):
        """測試成功根據短碼取得 URL"""
        url_obj = URLService.create_short_url(self.user1, "https://www.example.com")
        short_code = url_obj.short_code

        # 使用短碼查詢
        retrieved_url = URLService.get_url_by_code(short_code)

        self.assertEqual(retrieved_url.id, url_obj.id)
        self.assertEqual(retrieved_url.original_url, url_obj.original_url)

    def test_get_url_by_code_invalid(self):
        """測試無效的短碼"""
        with self.assertRaises(UrlNotFoundError):
            URLService.get_url_by_code("invalid_code")

        with self.assertRaises(UrlNotFoundError):
            URLService.get_url_by_code("")

    def test_get_url_by_code_not_found(self):
        """測試不存在的短碼"""
        # 建立有效格式但不存在的短碼
        from sqids import Sqids

        sqids = Sqids(min_length=6)
        fake_code = sqids.encode([99999, 99999])  # 不存在的 user_id 和 url_id

        with self.assertRaises(UrlNotFoundError):
            URLService.get_url_by_code(fake_code)

    def test_get_user_urls(self):
        """測試取得使用者的 URL 列表"""
        # 建立多個 URL
        url1 = URLService.create_short_url(self.user1, "https://example1.com")
        url2 = URLService.create_short_url(self.user1, "https://example2.com")
        url3 = URLService.create_short_url(self.user2, "https://example3.com")

        # 查詢 user1 的 URL
        user1_urls = URLService.get_user_urls(self.user1)

        self.assertEqual(user1_urls.count(), 2)
        self.assertIn(url1, user1_urls)
        self.assertIn(url2, user1_urls)
        self.assertNotIn(url3, user1_urls)

    def test_get_user_urls_with_stats(self):
        """測試取得含統計的 URL 列表"""
        url_obj = URLService.create_short_url(self.user1, "https://www.example.com")

        # 建立一些點擊記錄
        factory = RequestFactory()  # 建立 Django request 物件
        request = factory.get(f"/{url_obj.short_code}/")
        AnalyticsService.record_click(url_obj, request)
        AnalyticsService.record_click(url_obj, request)

        # 查詢含統計的 URL 列表
        urls = URLService.get_user_urls_with_stats(self.user1)

        self.assertEqual(urls.count(), 1)
        self.assertEqual(urls[0].click_count, 2)

    def test_verify_owner_success(self):
        """測試擁有者驗證通過"""
        url_obj = URLService.create_short_url(self.user1, "https://www.example.com")

        # 不應該拋出異常
        try:
            URLService.verify_owner(url_obj, self.user1)  # 成功時不會有例外
        except AccessDeniedError:
            self.fail("verify_owner raised AccessDeniedError unexpectedly")

    def test_verify_owner_denied(self):
        """測試非擁有者被拒絕"""
        url_obj = URLService.create_short_url(self.user1, "https://www.example.com")

        with self.assertRaises(AccessDeniedError):
            URLService.verify_owner(url_obj, self.user2)

    def test_different_users_same_url(self):
        """測試不同使用者縮同一網址產生不同短碼"""
        url1 = URLService.create_short_url(self.user1, "https://www.example.com")
        url2 = URLService.create_short_url(self.user2, "https://www.example.com")

        self.assertNotEqual(url1.short_code, url2.short_code)

    def test_get_or_create_short_url_new(self):
        """測試 get_or_create_short_url 建立新 URL"""
        url_obj, created = URLService.get_or_create_short_url(
            self.user1, "https://www.example.com"
        )

        self.assertTrue(created)
        self.assertIsNotNone(url_obj.id)
        self.assertIsNotNone(url_obj.short_code)
        self.assertEqual(url_obj.original_url, "https://www.example.com")
        self.assertEqual(url_obj.user, self.user1)

    def test_get_or_create_short_url_existing(self):
        """測試 get_or_create_short_url 返回已存在的 URL"""
        # 第一次建立
        url1, created1 = URLService.get_or_create_short_url(
            self.user1, "https://www.example.com"
        )
        self.assertTrue(created1)

        # 第二次應該返回相同的 URL
        url2, created2 = URLService.get_or_create_short_url(
            self.user1, "https://www.example.com"
        )
        self.assertFalse(created2)
        self.assertEqual(url1.id, url2.id)
        self.assertEqual(url1.short_code, url2.short_code)

        # 確認資料庫中只有一筆記錄
        urls = URLModel.objects.filter(
            user=self.user1, original_url="https://www.example.com"
        )
        self.assertEqual(urls.count(), 1)

    def test_get_or_create_short_url_different_users(self):
        """測試不同使用者可以縮短相同 URL"""
        url1, created1 = URLService.get_or_create_short_url(
            self.user1, "https://www.example.com"
        )
        url2, created2 = URLService.get_or_create_short_url(
            self.user2, "https://www.example.com"
        )

        # 兩個都應該是新建立的
        self.assertTrue(created1)
        self.assertTrue(created2)

        # ID 和短碼應該不同
        self.assertNotEqual(url1.id, url2.id)
        self.assertNotEqual(url1.short_code, url2.short_code)

        # 資料庫中應該有兩筆記錄
        total_urls = URLModel.objects.filter(original_url="https://www.example.com")
        self.assertEqual(total_urls.count(), 2)

    def test_get_or_create_short_url_invalid_format(self):
        """測試 get_or_create_short_url 拒絕無效 URL"""
        with self.assertRaises(ValidationError):
            URLService.get_or_create_short_url(self.user1, "not-a-valid-url")

        with self.assertRaises(ValidationError):
            URLService.get_or_create_short_url(self.user1, "")


class AnalyticsServiceTestCase(TestCase):
    """AnalyticsService 測試"""

    def setUp(self):
        """建立測試資料"""
        self.user = User.objects.create_user(username="testuser", password="pass123")
        self.url_obj = URLService.create_short_url(self.user, "https://www.example.com")
        self.factory = RequestFactory()

    def test_record_click_basic(self):
        """測試基本點擊記錄"""
        request = self.factory.get(f"/{self.url_obj.short_code}/")
        request.META["REMOTE_ADDR"] = "192.168.1.100"

        click_log = AnalyticsService.record_click(self.url_obj, request)

        self.assertIsNotNone(click_log.id)
        self.assertEqual(click_log.url, self.url_obj)
        self.assertEqual(click_log.ip_address, "192.168.1.100")
        self.assertIsNotNone(click_log.clicked_at)

    def test_record_click_with_forwarded_ip(self):
        """測試從 X-Forwarded-For 取得 IP"""
        request = self.factory.get(f"/{self.url_obj.short_code}/")
        request.META["HTTP_X_FORWARDED_FOR"] = "203.0.113.1, 192.168.1.1"
        request.META["REMOTE_ADDR"] = "192.168.1.100"

        click_log = AnalyticsService.record_click(self.url_obj, request)

        # 應該取第一個 IP
        self.assertEqual(click_log.ip_address, "203.0.113.1")

    def test_record_click_with_user_agent(self):
        """測試 User-Agent 解析"""
        request = self.factory.get(f"/{self.url_obj.short_code}/")
        request.META["REMOTE_ADDR"] = "192.168.1.100"
        request.META["HTTP_USER_AGENT"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )

        click_log = AnalyticsService.record_click(self.url_obj, request)

        # 應該有解析瀏覽器和 OS 資訊
        self.assertIsNotNone(click_log.browser)
        self.assertIsNotNone(click_log.os)
        self.assertIsNotNone(click_log.device_type)

    def test_record_click_with_referer(self):
        """測試記錄 Referer"""
        request = self.factory.get(f"/{self.url_obj.short_code}/")
        request.META["REMOTE_ADDR"] = "192.168.1.100"
        request.META["HTTP_REFERER"] = "https://www.google.com"

        click_log = AnalyticsService.record_click(self.url_obj, request)

        self.assertEqual(click_log.referer, "https://www.google.com")

    def test_get_url_stats(self):
        """測試取得統計資料"""
        # 建立多筆點擊記錄
        request = self.factory.get(f"/{self.url_obj.short_code}/")
        request.META["REMOTE_ADDR"] = "192.168.1.100"

        AnalyticsService.record_click(self.url_obj, request)
        AnalyticsService.record_click(self.url_obj, request)
        AnalyticsService.record_click(self.url_obj, request)

        stats = AnalyticsService.get_url_stats(self.url_obj)

        self.assertEqual(stats["total_clicks"], 3)
        self.assertEqual(len(stats["clicks"]), 3)
        self.assertIn("clicked_at", stats["clicks"][0])
        self.assertIn("ip_address", stats["clicks"][0])

    def test_anonymize_ip_ipv4(self):
        """測試 IPv4 匿名化"""
        ip = "192.168.1.100"
        anonymized = AnalyticsService.anonymize_ip(ip)

        self.assertEqual(anonymized, "192.168.1.0")

    def test_anonymize_ip_ipv6(self):
        """測試 IPv6 匿名化"""
        ip = "2001:0db8:85a3:0000:0000:8a2e:0370:7334"
        anonymized = AnalyticsService.anonymize_ip(ip)

        # 應該只保留前 4 段
        self.assertTrue(anonymized.startswith("2001:0db8:85a3:0000::"))

    def test_get_url_stats_anonymized_ip(self):
        """測試統計資料中的 IP 已匿名化"""
        request = self.factory.get(f"/{self.url_obj.short_code}/")
        request.META["REMOTE_ADDR"] = "192.168.1.100"

        AnalyticsService.record_click(self.url_obj, request)
        stats = AnalyticsService.get_url_stats(self.url_obj)

        # 統計資料中的 IP 應該是匿名化的
        self.assertEqual(stats["clicks"][0]["ip_address"], "192.168.1.0")


class ViewTestCase(TestCase):
    """View 層測試"""

    def setUp(self):
        """建立測試資料"""
        self.user1 = User.objects.create_user(username="user1", password="pass123")
        self.user2 = User.objects.create_user(username="user2", password="pass123")
        self.client = Client()

    def test_home_view(self):
        """測試首頁"""
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "URL Shortener")

    def test_my_urls_view_requires_login(self):
        """測試我的網址頁需要登入"""
        response = self.client.get(reverse("my_urls"))

        # 應該重定向到登入頁
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_my_urls_view_authenticated(self):
        """測試已登入使用者可以訪問我的網址頁"""
        self.client.login(username="user1", password="pass123")
        response = self.client.get(reverse("my_urls"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "My URLs")

    def test_create_short_url(self):
        """測試建立短網址"""
        self.client.login(username="user1", password="pass123")

        response = self.client.post(
            reverse("my_urls"), {"original_url": "https://www.example.com"}
        )

        # 應該重定向回我的網址頁
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("my_urls"))

        # 確認 URL 已建立
        urls = URLModel.objects.filter(user=self.user1)
        self.assertEqual(urls.count(), 1)
        self.assertEqual(urls[0].original_url, "https://www.example.com")

    def test_create_short_url_invalid(self):
        """測試建立無效的短網址"""
        self.client.login(username="user1", password="pass123")

        response = self.client.post(
            reverse("my_urls"), {"original_url": "not-a-valid-url"}
        )

        # 應該重定向回我的網址頁
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("my_urls"))

        # Follow redirect 並檢查錯誤訊息
        response = self.client.get(response.url)
        self.assertEqual(response.status_code, 200)
        # 檢查 messages 中是否包含錯誤訊息
        messages_list = list(response.context["messages"])
        self.assertTrue(
            any(
                "Invalid URL format" in str(m) or "Enter a valid URL" in str(m)
                for m in messages_list
            )
        )

    def test_redirect_view_success(self):
        """測試短網址重定向"""
        url_obj = URLService.create_short_url(self.user1, "https://www.example.com")

        response = self.client.get(reverse("redirect", args=[url_obj.short_code]))

        # 應該是 302 重定向
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "https://www.example.com")

        # 確認點擊已記錄
        self.assertEqual(ClickLog.objects.filter(url=url_obj).count(), 1)

    def test_redirect_view_not_found(self):
        """測試不存在的短網址"""
        response = self.client.get(reverse("redirect", args=["invalid_code"]))

        self.assertEqual(response.status_code, 404)

    def test_url_stats_view_requires_login(self):
        """測試統計頁需要登入"""
        url_obj = URLService.create_short_url(self.user1, "https://www.example.com")

        response = self.client.get(reverse("url_stats", args=[url_obj.short_code]))

        # 應該重定向到登入頁
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_url_stats_view_owner_access(self):
        """測試擁有者可以訪問統計頁"""
        self.client.login(username="user1", password="pass123")
        url_obj = URLService.create_short_url(self.user1, "https://www.example.com")

        response = self.client.get(reverse("url_stats", args=[url_obj.short_code]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "URL Statistics")
        self.assertContains(response, url_obj.original_url)

    def test_url_stats_view_non_owner_denied(self):
        """測試非擁有者無法訪問統計頁"""
        self.client.login(username="user2", password="pass123")
        url_obj = URLService.create_short_url(self.user1, "https://www.example.com")

        response = self.client.get(reverse("url_stats", args=[url_obj.short_code]))

        # 應該重定向回我的網址頁
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("my_urls"))

        # Follow redirect 並檢查錯誤訊息
        response = self.client.get(response.url)
        self.assertEqual(response.status_code, 200)
        messages_list = list(response.context["messages"])
        self.assertTrue(
            any(
                "You do not have permission to view this URL" in str(m)
                for m in messages_list
            )
        )

    def test_url_stats_view_not_found(self):
        """測試統計頁不存在的短碼"""
        self.client.login(username="user1", password="pass123")

        response = self.client.get(reverse("url_stats", args=["invalid_code"]))

        # 應該重定向回我的網址頁
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("my_urls"))

        # Follow redirect 並檢查錯誤訊息
        response = self.client.get(response.url)
        self.assertEqual(response.status_code, 200)
        messages_list = list(response.context["messages"])
        self.assertTrue(
            any("Short URL not found" in str(m) for m in messages_list)
        )

    def test_user_isolation(self):
        """測試使用者資料隔離"""
        self.client.login(username="user1", password="pass123")

        # user1 建立 URL
        URLService.create_short_url(self.user1, "https://example1.com")

        # user2 建立 URL
        URLService.create_short_url(self.user2, "https://example2.com")

        # user1 訪問我的網址頁
        response = self.client.get(reverse("my_urls"))

        # 應該只看到自己的 URL
        self.assertContains(response, "example1.com")
        self.assertNotContains(response, "example2.com")


class URLToggleAndFilterTestCase(TestCase):
    """URL Toggle 和 Filter/Sort 功能測試"""

    def setUp(self):
        """建立測試資料"""
        self.user1 = User.objects.create_user(username="user1", password="pass123")
        self.user2 = User.objects.create_user(username="user2", password="pass123")
        self.client = Client()

        # 建立多個測試 URL
        self.url1 = URLService.create_short_url(self.user1, "https://zzz-example.com")
        self.url2 = URLService.create_short_url(self.user1, "https://aaa-example.com")
        self.url3 = URLService.create_short_url(self.user1, "https://mmm-example.com")

    # ============ Service Layer - Toggle Tests ============

    def test_toggle_url_status_active_to_inactive(self):
        """測試切換 URL 從啟用到停用"""
        self.assertTrue(self.url1.is_active)

        toggled = URLService.toggle_url_status(self.url1.id, self.user1)

        self.assertFalse(toggled.is_active)
        # 重新從資料庫載入確認
        self.url1.refresh_from_db()
        self.assertFalse(self.url1.is_active)

    def test_toggle_url_status_inactive_to_active(self):
        """測試切換 URL 從停用到啟用"""
        # 先停用
        self.url1.is_active = False
        self.url1.save()

        toggled = URLService.toggle_url_status(self.url1.id, self.user1)

        self.assertTrue(toggled.is_active)
        self.url1.refresh_from_db()
        self.assertTrue(self.url1.is_active)

    def test_toggle_url_status_non_owner(self):
        """測試非擁有者無法 toggle"""
        with self.assertRaises(AccessDeniedError):
            URLService.toggle_url_status(self.url1.id, self.user2)

        # URL 狀態應該沒有改變
        self.url1.refresh_from_db()
        self.assertTrue(self.url1.is_active)

    def test_toggle_url_status_not_found(self):
        """測試 toggle 不存在的 URL"""
        with self.assertRaises(UrlNotFoundError):
            URLService.toggle_url_status(99999, self.user1)

    # ============ Service Layer - Filter Tests ============

    def test_get_filtered_urls_by_status_active(self):
        """測試篩選啟用的 URL"""
        # 停用一個 URL
        self.url2.is_active = False
        self.url2.save()

        urls = URLService.get_filtered_urls_with_stats(
            self.user1, status_filter="active"
        )

        self.assertEqual(urls.count(), 2)
        url_ids = [url.id for url in urls]
        self.assertIn(self.url1.id, url_ids)
        self.assertNotIn(self.url2.id, url_ids)
        self.assertIn(self.url3.id, url_ids)

    def test_get_filtered_urls_by_status_inactive(self):
        """測試篩選停用的 URL"""
        # 停用兩個 URL
        self.url1.is_active = False
        self.url1.save()
        self.url2.is_active = False
        self.url2.save()

        urls = URLService.get_filtered_urls_with_stats(
            self.user1, status_filter="inactive"
        )

        self.assertEqual(urls.count(), 2)
        url_ids = [url.id for url in urls]
        self.assertIn(self.url1.id, url_ids)
        self.assertIn(self.url2.id, url_ids)
        self.assertNotIn(self.url3.id, url_ids)

    def test_get_filtered_urls_by_status_all(self):
        """測試顯示全部 URL（不篩選狀態）"""
        # 停用一個 URL
        self.url2.is_active = False
        self.url2.save()

        urls = URLService.get_filtered_urls_with_stats(self.user1, status_filter=None)

        self.assertEqual(urls.count(), 3)

    # ============ Service Layer - Sort Tests ============

    def test_get_filtered_urls_sort_by_created_at_desc(self):
        """測試按建立時間降序排序"""
        urls = URLService.get_filtered_urls_with_stats(
            self.user1, sort_by="created_at", sort_order="desc"
        )

        # url3 是最後建立的，應該排第一
        self.assertEqual(urls[0].id, self.url3.id)
        self.assertEqual(urls[2].id, self.url1.id)

    def test_get_filtered_urls_sort_by_created_at_asc(self):
        """測試按建立時間升序排序"""
        urls = URLService.get_filtered_urls_with_stats(
            self.user1, sort_by="created_at", sort_order="asc"
        )

        # url1 是最早建立的，應該排第一
        self.assertEqual(urls[0].id, self.url1.id)
        self.assertEqual(urls[2].id, self.url3.id)

    def test_get_filtered_urls_sort_by_original_url_asc(self):
        """測試按原始網址升序排序"""
        urls = URLService.get_filtered_urls_with_stats(
            self.user1, sort_by="original_url", sort_order="asc"
        )

        # aaa 應該排第一，zzz 排最後
        self.assertEqual(urls[0].original_url, "https://aaa-example.com")
        self.assertEqual(urls[1].original_url, "https://mmm-example.com")
        self.assertEqual(urls[2].original_url, "https://zzz-example.com")

    def test_get_filtered_urls_sort_by_original_url_desc(self):
        """測試按原始網址降序排序"""
        urls = URLService.get_filtered_urls_with_stats(
            self.user1, sort_by="original_url", sort_order="desc"
        )

        # zzz 應該排第一，aaa 排最後
        self.assertEqual(urls[0].original_url, "https://zzz-example.com")
        self.assertEqual(urls[1].original_url, "https://mmm-example.com")
        self.assertEqual(urls[2].original_url, "https://aaa-example.com")

    def test_get_filtered_urls_combined_filter_and_sort(self):
        """測試組合篩選和排序"""
        # 停用 url1 (zzz)
        self.url1.is_active = False
        self.url1.save()

        urls = URLService.get_filtered_urls_with_stats(
            self.user1, status_filter="active", sort_by="original_url", sort_order="asc"
        )

        # 只有兩個啟用的 URL，按字母順序排列
        self.assertEqual(urls.count(), 2)
        self.assertEqual(urls[0].original_url, "https://aaa-example.com")
        self.assertEqual(urls[1].original_url, "https://mmm-example.com")

    # ============ Service Layer - check_active Tests ============

    def test_get_url_by_code_check_active_true_for_inactive_url(self):
        """測試 check_active=True 時停用的 URL 拋出異常"""
        # 停用 URL
        self.url1.is_active = False
        self.url1.save()

        with self.assertRaises(UrlNotFoundError):
            URLService.get_url_by_code(self.url1.short_code, check_active=True)

    def test_get_url_by_code_check_active_false_for_inactive_url(self):
        """測試 check_active=False 時停用的 URL 可以取得"""
        # 停用 URL
        self.url1.is_active = False
        self.url1.save()

        # 應該可以取得
        url_obj = URLService.get_url_by_code(self.url1.short_code, check_active=False)

        self.assertEqual(url_obj.id, self.url1.id)
        self.assertFalse(url_obj.is_active)

    def test_get_url_by_code_check_active_true_for_active_url(self):
        """測試 check_active=True 時啟用的 URL 正常取得"""
        url_obj = URLService.get_url_by_code(self.url1.short_code, check_active=True)

        self.assertEqual(url_obj.id, self.url1.id)
        self.assertTrue(url_obj.is_active)

    # ============ View Layer - Toggle Tests ============

    def test_toggle_url_view_success(self):
        """測試 toggle view 成功切換狀態"""
        self.client.login(username="user1", password="pass123")

        response = self.client.post(reverse("toggle_url", args=[self.url1.id]))

        # 應該重定向回 my_urls
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("my_urls"))

        # URL 應該被停用
        self.url1.refresh_from_db()
        self.assertFalse(self.url1.is_active)

    def test_toggle_url_view_non_owner(self):
        """測試非擁有者無法 toggle"""
        self.client.login(username="user2", password="pass123")

        response = self.client.post(reverse("toggle_url", args=[self.url1.id]))

        # 應該重定向並顯示錯誤訊息
        self.assertEqual(response.status_code, 302)

        # URL 狀態應該沒有改變
        self.url1.refresh_from_db()
        self.assertTrue(self.url1.is_active)

    def test_toggle_url_view_requires_login(self):
        """測試 toggle view 需要登入"""
        response = self.client.post(reverse("toggle_url", args=[self.url1.id]))

        # 應該重定向到登入頁
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_toggle_url_view_get_not_allowed(self):
        """測試 toggle view 不接受 GET 請求"""
        self.client.login(username="user1", password="pass123")

        response = self.client.get(reverse("toggle_url", args=[self.url1.id]))

        # 應該重定向並顯示錯誤訊息
        self.assertEqual(response.status_code, 302)

    # ============ View Layer - Filter Tests ============

    def test_my_urls_view_with_status_filter_active(self):
        """測試 my_urls view 的狀態篩選（active）"""
        self.client.login(username="user1", password="pass123")

        # 停用一個 URL
        self.url2.is_active = False
        self.url2.save()

        response = self.client.get(reverse("my_urls") + "?status=active")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.url1.short_code)
        self.assertNotContains(response, self.url2.short_code)
        self.assertContains(response, self.url3.short_code)

    def test_my_urls_view_with_status_filter_inactive(self):
        """測試 my_urls view 的狀態篩選（inactive）"""
        self.client.login(username="user1", password="pass123")

        # 停用一個 URL
        self.url2.is_active = False
        self.url2.save()

        response = self.client.get(reverse("my_urls") + "?status=inactive")

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.url1.short_code)
        self.assertContains(response, self.url2.short_code)
        self.assertNotContains(response, self.url3.short_code)

    def test_my_urls_view_with_sorting(self):
        """測試 my_urls view 的排序功能"""
        self.client.login(username="user1", password="pass123")

        response = self.client.get(
            reverse("my_urls") + "?sort_by=original_url&order=asc"
        )

        self.assertEqual(response.status_code, 200)
        # 檢查排序是否正確（aaa 應該在 zzz 前面）
        content = response.content.decode()
        aaa_pos = content.find("aaa-example.com")
        zzz_pos = content.find("zzz-example.com")
        self.assertLess(aaa_pos, zzz_pos)

    # ============ Integration Tests ============

    def test_disabled_url_returns_404(self):
        """測試停用的 URL 訪問時返回 404"""
        # 停用 URL
        self.url1.is_active = False
        self.url1.save()

        response = self.client.get(reverse("redirect", args=[self.url1.short_code]))

        # 應該返回 404
        self.assertEqual(response.status_code, 404)

    def test_owner_can_view_disabled_url_stats(self):
        """測試擁有者可以查看停用 URL 的統計"""
        self.client.login(username="user1", password="pass123")

        # 停用 URL
        self.url1.is_active = False
        self.url1.save()

        response = self.client.get(reverse("url_stats", args=[self.url1.short_code]))

        # 應該可以訪問
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "URL Statistics")
        self.assertContains(response, self.url1.original_url)
