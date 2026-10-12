"""Ad rotation and the paid "remove ads" entitlement.

Payments go through RevenueCat, with Paddle Billing as the checkout behind
RevenueCat's Web Purchase Links. RevenueCat has no Windows/desktop SDK, so
the app talks to it the same way its JavaScript SDK does:

1. Each install gets a random App User ID (persisted in license.json).
2. Buying opens a RevenueCat Web Purchase Link in the browser, with that ID
   appended as a path segment (https://pay.rev.cat/<token>/<app_user_id>),
   so the purchase is attributed to this install without any login.
3. The app then polls GET /v1/subscribers/<app_user_id> with the public
   API key until the configured entitlement is active. The public key is
   meant to ship inside client apps - it can read a customer's own
   entitlements but can't grant anything.

Why Paddle rather than RevenueCat's own Web Billing: Web Billing runs on
Stripe, which doesn't onboard businesses based in Turkey. Paddle does, and
acts as merchant of record (it collects VAT/sales tax worldwide and pays out
to a Turkish bank account or Payoneer). See MONETIZATION_SETUP.md.

The last confirmed entitlement is cached so the app stays ad-free offline:
a lifetime unlock forever, a subscription until its expiry date plus
OFFLINE_GRACE.
"""

import json
import threading
import time
import uuid
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

REVENUECAT_API_BASE = "https://api.revenuecat.com/v1"
USER_AGENT = "BatteryTrayMonitor/1.0"
HTTP_TIMEOUT_SECONDS = 15

# How long a cached subscription keeps the app ad-free past its expiry date
# when RevenueCat can't be reached (laptop offline, API outage) - long
# enough that a renewal that already happened server-side isn't punished.
OFFLINE_GRACE = timedelta(days=3)
RECHECK_INTERVAL_SECONDS = 6 * 60 * 60
# After opening the checkout, poll this often for this long - Paddle
# usually confirms within seconds, but card 3-D Secure steps can take a
# few minutes.
PURCHASE_POLL_SECONDS = 4
PURCHASE_POLL_TIMEOUT_SECONDS = 20 * 60

AD_TEXT_MAX_LENGTH = 100
REMOVE_ADS_URL = "app:remove-ads"

PLAN_SUBSCRIPTION = "subscription"
PLAN_LIFETIME = "lifetime"


@dataclass
class MonetizationConfig:
    revenuecat_public_api_key: str = ""
    entitlement_id: str = "no_ads"
    subscription_purchase_link: str = ""
    lifetime_purchase_link: str = ""
    subscription_price_label: str = "$5 / year"
    lifetime_price_label: str = "$15 one-time"
    ads_feed_url: str = ""
    house_ads: list = field(default_factory=list)

    @property
    def payments_configured(self):
        return bool(
            self.revenuecat_public_api_key
            and self.entitlement_id
            and (self.subscription_purchase_link or self.lifetime_purchase_link)
        )

    def purchase_link(self, plan):
        if plan == PLAN_SUBSCRIPTION:
            return self.subscription_purchase_link
        if plan == PLAN_LIFETIME:
            return self.lifetime_purchase_link
        raise ValueError(f"unknown plan {plan!r}")


def load_config(path):
    config = MonetizationConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return config
    if not isinstance(data, dict):
        return config
    for name in (
        "revenuecat_public_api_key", "entitlement_id", "subscription_purchase_link",
        "lifetime_purchase_link", "subscription_price_label", "lifetime_price_label",
        "ads_feed_url",
    ):
        value = data.get(name)
        if isinstance(value, str):
            setattr(config, name, value.strip())
    config.house_ads = _clean_ads(data.get("house_ads"))
    return config


def _parse_time(value):
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _format_time(value):
    return value.astimezone(timezone.utc).isoformat() if value else None


def _now():
    return datetime.now(timezone.utc)


def is_valid_app_user_id(value):
    return (
        isinstance(value, str)
        and 0 < len(value) <= 100
        and not any(c.isspace() for c in value)
        and "/" not in value
    )


def _http_get_json(url, headers=None):
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})})
    with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_entitlement(subscriber_response, entitlement_id):
    """Extracts the cached-entitlement record from a /v1/subscribers
    response, or None if the customer never had the entitlement. The
    record is kept even once expired, so the dialog can say "your
    subscription ended" and the offline check has something to compare."""
    subscriber = (subscriber_response or {}).get("subscriber") or {}
    entitlement = (subscriber.get("entitlements") or {}).get(entitlement_id)
    if not entitlement:
        return None
    expires = _parse_time(entitlement.get("expires_date"))
    grace = _parse_time(entitlement.get("grace_period_expires_date"))
    if expires and grace and grace > expires:
        expires = grace
    return {
        "lifetime": entitlement.get("expires_date") is None,
        "expires_date": _format_time(expires),
        "product": entitlement.get("product_identifier"),
        "management_url": subscriber.get("management_url"),
    }


def entitlement_active(record, now=None, offline=False):
    if not record:
        return False
    if record.get("lifetime"):
        return True
    expires = _parse_time(record.get("expires_date"))
    if expires is None:
        return False
    if offline:
        expires += OFFLINE_GRACE
    return (now or _now()) < expires


class LicenseManager:
    """Owns this install's App User ID and whether it's currently ad-free.
    All network calls run on background threads; listeners are called from
    those threads with no arguments whenever the ad-free state, plan or
    status message changes, and must hand off to the UI thread themselves."""

    def __init__(self, config, path):
        self.config = config
        self.path = path
        self._lock = threading.Lock()
        self._listeners = []
        self._app_user_id = None
        self._entitlement = None
        self._offline = True
        self._last_error = None
        self._polling_until = 0.0
        self._load()

    # --- persistence ---

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        app_user_id = data.get("app_user_id")
        if not is_valid_app_user_id(app_user_id):
            app_user_id = "btm_" + uuid.uuid4().hex
        self._app_user_id = app_user_id
        entitlement = data.get("entitlement")
        self._entitlement = entitlement if isinstance(entitlement, dict) else None
        self._save()

    def _save(self):
        try:
            self.path.write_text(json.dumps({
                "app_user_id": self._app_user_id,
                "entitlement": self._entitlement,
            }, indent=2), encoding="utf-8")
        except OSError:
            pass

    # --- state ---

    def add_listener(self, callback):
        self._listeners.append(callback)

    def _notify(self):
        for callback in list(self._listeners):
            try:
                callback()
            except Exception:
                pass

    @property
    def app_user_id(self):
        with self._lock:
            return self._app_user_id

    @property
    def ad_free(self):
        with self._lock:
            return entitlement_active(self._entitlement, offline=self._offline)

    def status(self):
        with self._lock:
            entitlement = dict(self._entitlement) if self._entitlement else None
            return {
                "ad_free": entitlement_active(entitlement, offline=self._offline),
                "lifetime": bool(entitlement and entitlement.get("lifetime")),
                "expires": _parse_time(entitlement.get("expires_date")) if entitlement else None,
                "management_url": entitlement.get("management_url") if entitlement else None,
                "had_entitlement": entitlement is not None,
                "waiting_for_payment": time.monotonic() < self._polling_until,
                "last_error": self._last_error,
            }

    # --- RevenueCat ---

    def check_now(self):
        """Blocking entitlement fetch. Returns True if the server answered."""
        if not self.config.revenuecat_public_api_key:
            return False
        app_user_id = self.app_user_id
        url = f"{REVENUECAT_API_BASE}/subscribers/{quote(app_user_id, safe='')}"
        try:
            response = _http_get_json(url, {
                "Authorization": f"Bearer {self.config.revenuecat_public_api_key}",
            })
        except HTTPError as e:
            error = "RevenueCat rejected the API key." if e.code in (401, 403) else f"RevenueCat error (HTTP {e.code})."
            self._set_offline(error)
            return False
        except (URLError, OSError, ValueError):
            self._set_offline("Couldn't reach RevenueCat - check your internet connection.")
            return False

        entitlement = parse_entitlement(response, self.config.entitlement_id)
        with self._lock:
            if app_user_id != self._app_user_id:
                # restore() switched IDs mid-request; this answer is stale.
                return True
            changed = entitlement != self._entitlement or self._offline or self._last_error
            self._entitlement = entitlement
            self._offline = False
            self._last_error = None
            if entitlement_active(entitlement):
                self._polling_until = 0.0
            self._save()
        if changed:
            self._notify()
        return True

    def _set_offline(self, error):
        with self._lock:
            changed = not self._offline or self._last_error != error
            self._offline = True
            self._last_error = error
        if changed:
            self._notify()

    def refresh_async(self):
        threading.Thread(target=self.check_now, daemon=True).start()

    def start(self):
        """Checks once now, then every RECHECK_INTERVAL_SECONDS, so a
        subscription that lapses (or renews) is picked up without a
        restart."""
        def loop():
            while True:
                self.check_now()
                time.sleep(RECHECK_INTERVAL_SECONDS)

        threading.Thread(target=loop, daemon=True).start()

    def start_purchase(self, plan):
        """Opens the checkout for `plan` in the browser and starts polling
        for the entitlement. Returns an error message, or None on success."""
        link = self.config.purchase_link(plan)
        if not self.config.revenuecat_public_api_key or not link:
            return "Payments aren't set up in this build yet."
        parsed = urlparse(link)
        if parsed.scheme != "https":
            return "The purchase link in monetization_config.json must start with https://."
        url = f"{link.rstrip('/')}/{quote(self.app_user_id, safe='')}"
        if not webbrowser.open(url):
            return f"Couldn't open your browser. Visit this link to pay:\n{url}"
        self._start_polling()
        return None

    def _start_polling(self):
        with self._lock:
            already_polling = time.monotonic() < self._polling_until
            self._polling_until = time.monotonic() + PURCHASE_POLL_TIMEOUT_SECONDS
        self._notify()
        if already_polling:
            return

        def poll():
            while True:
                time.sleep(PURCHASE_POLL_SECONDS)
                with self._lock:
                    if time.monotonic() >= self._polling_until:
                        break
                self.check_now()
            self._notify()

        threading.Thread(target=poll, daemon=True).start()

    def restore(self, app_user_id):
        """Switches this install to the License ID from another install
        (e.g. after reinstalling Windows), then re-checks. Returns an error
        message, or None if the ID was accepted."""
        app_user_id = (app_user_id or "").strip()
        if not is_valid_app_user_id(app_user_id):
            return "That doesn't look like a License ID."
        with self._lock:
            self._app_user_id = app_user_id
            self._entitlement = None
            self._save()
        self._notify()
        self.refresh_async()
        return None


def _clean_ads(raw):
    if isinstance(raw, dict):
        raw = raw.get("ads")
    if not isinstance(raw, list):
        return []
    ads = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text, url = item.get("text"), item.get("url")
        if not isinstance(text, str) or not text.strip() or not isinstance(url, str):
            continue
        url = url.strip()
        # Only web links (or the built-in "open the Remove ads dialog"
        # action) - the feed is remote content, and webbrowser.open would
        # happily launch file:// paths or other protocol handlers.
        if url != REMOVE_ADS_URL and urlparse(url).scheme not in ("http", "https"):
            continue
        text = " ".join(text.split())
        if len(text) > AD_TEXT_MAX_LENGTH:
            text = text[:AD_TEXT_MAX_LENGTH - 1].rstrip() + "…"
        ads.append({"text": text, "url": url})
    return ads


class AdProvider:
    """Rotates through text ads: the house ads bundled in
    monetization_config.json, replaced by the ads from `ads_feed_url` (a
    JSON list of {"text", "url"}, or {"ads": [...]}) once that loads - so
    ad copy can be changed or sold without shipping a new exe."""

    def __init__(self, config):
        self.config = config
        self._lock = threading.Lock()
        self._ads = list(config.house_ads) or [
            {"text": "Remove ads and support development.", "url": REMOVE_ADS_URL},
        ]
        self._index = -1

    def refresh_async(self):
        if not self.config.ads_feed_url:
            return

        def worker():
            while True:
                try:
                    ads = _clean_ads(_http_get_json(self.config.ads_feed_url))
                except (URLError, OSError, ValueError):
                    ads = []
                if ads:
                    with self._lock:
                        self._ads = ads
                        self._index = -1
                time.sleep(RECHECK_INTERVAL_SECONDS)

        threading.Thread(target=worker, daemon=True).start()

    def next_ad(self):
        with self._lock:
            self._index = (self._index + 1) % len(self._ads)
            return dict(self._ads[self._index])


def open_ad(ad):
    if urlparse(ad["url"]).scheme in ("http", "https"):
        webbrowser.open(ad["url"])
