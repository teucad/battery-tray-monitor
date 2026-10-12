"""Unit tests for monetization.py - no network, no RevenueCat account needed.

Run from the battery-tray-monitor folder:
    python -m unittest discover -s tests
"""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import monetization  # noqa: E402

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def subscriber(entitlements, management_url=None):
    return {"subscriber": {"entitlements": entitlements, "management_url": management_url}}


def configured(**overrides):
    values = dict(
        revenuecat_public_api_key="pdl_public_test",
        entitlement_id="no_ads",
        subscription_purchase_link="https://pay.rev.cat/subtoken",
        lifetime_purchase_link="https://pay.rev.cat/lifetoken/",
    )
    values.update(overrides)
    return monetization.MonetizationConfig(**values)


class EntitlementParsingTests(unittest.TestCase):
    def test_lifetime_purchase_never_expires(self):
        record = monetization.parse_entitlement(
            subscriber({"no_ads": {"expires_date": None, "product_identifier": "lifetime"}}), "no_ads",
        )
        self.assertTrue(record["lifetime"])
        self.assertTrue(monetization.entitlement_active(record, now=NOW + timedelta(days=3650)))

    def test_subscription_active_until_expiry(self):
        expires = NOW + timedelta(days=10)
        record = monetization.parse_entitlement(
            subscriber({"no_ads": {"expires_date": iso(expires)}}, "https://paddle.example/manage"), "no_ads",
        )
        self.assertFalse(record["lifetime"])
        self.assertEqual(record["management_url"], "https://paddle.example/manage")
        self.assertTrue(monetization.entitlement_active(record, now=NOW))
        self.assertFalse(monetization.entitlement_active(record, now=expires + timedelta(seconds=1)))

    def test_billing_grace_period_extends_expiry(self):
        expires, grace = NOW - timedelta(days=1), NOW + timedelta(days=5)
        record = monetization.parse_entitlement(
            subscriber({"no_ads": {"expires_date": iso(expires), "grace_period_expires_date": iso(grace)}}),
            "no_ads",
        )
        self.assertTrue(monetization.entitlement_active(record, now=NOW))

    def test_offline_grace_only_applies_offline(self):
        record = {"lifetime": False, "expires_date": iso(NOW - timedelta(days=1))}
        self.assertFalse(monetization.entitlement_active(record, now=NOW))
        self.assertTrue(monetization.entitlement_active(record, now=NOW, offline=True))
        later = NOW + monetization.OFFLINE_GRACE
        self.assertFalse(monetization.entitlement_active(record, now=later, offline=True))

    def test_other_entitlement_or_none(self):
        self.assertIsNone(monetization.parse_entitlement(subscriber({"pro": {"expires_date": None}}), "no_ads"))
        self.assertIsNone(monetization.parse_entitlement({}, "no_ads"))
        self.assertFalse(monetization.entitlement_active(None))


class ConfigTests(unittest.TestCase):
    def test_missing_or_broken_file_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.json"
            self.assertFalse(monetization.load_config(path).payments_configured)
            path.write_text("{not json")
            self.assertEqual(monetization.load_config(path).entitlement_id, "no_ads")

    def test_bundled_config_loads(self):
        path = Path(__file__).resolve().parent.parent / "monetization_config.json"
        config = monetization.load_config(path)
        self.assertEqual(config.subscription_price_label, "$5 / year")
        self.assertEqual(config.lifetime_price_label, "$15 one-time")
        self.assertTrue(config.house_ads)

    def test_payments_configured_needs_key_and_a_link(self):
        self.assertTrue(configured().payments_configured)
        self.assertFalse(configured(revenuecat_public_api_key="").payments_configured)
        self.assertFalse(configured(subscription_purchase_link="", lifetime_purchase_link="").payments_configured)


class AdTests(unittest.TestCase):
    def test_feed_cleaning_rejects_non_web_links(self):
        ads = monetization._clean_ads({"ads": [
            {"text": "ok", "url": "https://example.com"},
            {"text": "local file", "url": "file:///C:/Windows/System32/calc.exe"},
            {"text": "script", "url": "javascript:alert(1)"},
            {"text": "protocol handler", "url": "ms-settings:"},
            {"text": "upsell", "url": "app:remove-ads"},
            {"text": "", "url": "https://example.com"},
            "garbage",
        ]})
        self.assertEqual([a["text"] for a in ads], ["ok", "upsell"])

    def test_long_text_truncated(self):
        ads = monetization._clean_ads([{"text": "x" * 500, "url": "https://example.com"}])
        self.assertEqual(len(ads[0]["text"]), monetization.AD_TEXT_MAX_LENGTH)

    def test_rotation_cycles(self):
        provider = monetization.AdProvider(monetization.MonetizationConfig(house_ads=[
            {"text": "a", "url": "https://a.example"}, {"text": "b", "url": "https://b.example"},
        ]))
        self.assertEqual([provider.next_ad()["text"] for _ in range(3)], ["a", "b", "a"])

    def test_no_house_ads_still_has_upsell(self):
        provider = monetization.AdProvider(monetization.MonetizationConfig())
        self.assertEqual(provider.next_ad()["url"], monetization.REMOVE_ADS_URL)


class LicenseManagerTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "license.json"

    def tearDown(self):
        self.dir.cleanup()

    def test_app_user_id_generated_and_persisted(self):
        first = monetization.LicenseManager(configured(), self.path).app_user_id
        self.assertTrue(first.startswith("btm_"))
        self.assertEqual(monetization.LicenseManager(configured(), self.path).app_user_id, first)

    def test_check_now_grants_and_caches_entitlement(self):
        manager = monetization.LicenseManager(configured(), self.path)
        self.assertFalse(manager.ad_free)
        response = subscriber({"no_ads": {"expires_date": None}})
        with mock.patch.object(monetization, "_http_get_json", return_value=response) as get:
            self.assertTrue(manager.check_now())
        url, headers = get.call_args[0]
        self.assertEqual(url, f"https://api.revenuecat.com/v1/subscribers/{manager.app_user_id}")
        self.assertEqual(headers["Authorization"], "Bearer pdl_public_test")
        self.assertTrue(manager.ad_free)
        # Survives a restart while offline.
        self.assertTrue(monetization.LicenseManager(configured(), self.path).ad_free)

    def test_expired_subscription_removes_ad_free(self):
        manager = monetization.LicenseManager(configured(), self.path)
        expired = subscriber({"no_ads": {"expires_date": "2020-01-01T00:00:00Z"}})
        with mock.patch.object(monetization, "_http_get_json", return_value=expired):
            manager.check_now()
        self.assertFalse(manager.ad_free)
        self.assertTrue(manager.status()["had_entitlement"])

    def test_network_and_auth_errors_reported(self):
        manager = monetization.LicenseManager(configured(), self.path)
        with mock.patch.object(monetization, "_http_get_json", side_effect=URLError("down")):
            self.assertFalse(manager.check_now())
        self.assertIn("internet", manager.status()["last_error"])
        error = HTTPError("u", 401, "Unauthorized", {}, None)
        with mock.patch.object(monetization, "_http_get_json", side_effect=error):
            manager.check_now()
        self.assertIn("API key", manager.status()["last_error"])

    def test_listeners_notified_on_change(self):
        manager = monetization.LicenseManager(configured(), self.path)
        calls = []
        manager.add_listener(lambda: calls.append(1))
        with mock.patch.object(monetization, "_http_get_json", return_value=subscriber({})):
            manager.check_now()
        self.assertEqual(len(calls), 1)

    def test_start_purchase_opens_link_with_app_user_id(self):
        manager = monetization.LicenseManager(configured(), self.path)
        with mock.patch.object(monetization.webbrowser, "open", return_value=True) as open_, \
                mock.patch.object(monetization.LicenseManager, "_start_polling") as poll:
            self.assertIsNone(manager.start_purchase(monetization.PLAN_LIFETIME))
        open_.assert_called_once_with(f"https://pay.rev.cat/lifetoken/{manager.app_user_id}")
        poll.assert_called_once()

    def test_start_purchase_unconfigured_or_unsafe_link(self):
        unconfigured = monetization.LicenseManager(monetization.MonetizationConfig(), self.path)
        self.assertIn("aren't set up", unconfigured.start_purchase(monetization.PLAN_SUBSCRIPTION))
        insecure = monetization.LicenseManager(configured(subscription_purchase_link="http://x.example"), self.path)
        self.assertIn("https", insecure.start_purchase(monetization.PLAN_SUBSCRIPTION))

    def test_restore_switches_id(self):
        manager = monetization.LicenseManager(configured(), self.path)
        self.assertIsNotNone(manager.restore("has spaces"))
        self.assertIsNotNone(manager.restore("a/b"))
        with mock.patch.object(manager, "refresh_async"):
            self.assertIsNone(manager.restore("  btm_abc123  "))
        self.assertEqual(manager.app_user_id, "btm_abc123")
        self.assertEqual(json.loads(self.path.read_text())["app_user_id"], "btm_abc123")


if __name__ == "__main__":
    unittest.main()
