# Ads & "Remove ads" payments — setup guide

The app shows a small text ad at the bottom of the battery popup. Users can remove it with one of two plans:

| Plan | Configured label | Grants |
|---|---|---|
| Yearly subscription | `$5 / year` | `no_ads` entitlement while the subscription is active |
| Lifetime (one-time) | `$15 one-time` | `no_ads` entitlement forever |

Payments run through **RevenueCat**, with **Paddle Billing** as the payment processor behind RevenueCat's hosted checkout (Web Purchase Links).

## Why Paddle (receiving payments in Turkey)

RevenueCat can put two different payment processors behind its web checkout:

- **RevenueCat Web Billing** runs on **Stripe**. Stripe doesn't onboard businesses based in Turkey, so you can't use this option.
- **Paddle Billing** accepts sellers based in Turkey. Turkey isn't on Paddle's list of unsupported countries. Paddle is the *merchant of record*: it charges the buyer, collects and remits VAT and sales tax in every country, handles refunds and chargebacks, and sends you payouts.

Paddle pays out monthly once your balance is over $100. It pays by bank wire (SWIFT, about $15 per payout) to a Turkish bank account, or through **Payoneer**. You still report what Paddle pays you as income in Turkey. Ask a *mali müşavir* (accountant) how to register and declare it.

## What you keep per sale

Paddle charges **5% + $0.50** per transaction and has a **$0.70 minimum charge**. Both plans are well above that minimum:

| Plan | Price | Paddle fee | You keep |
|---|---|---|---|
| Yearly | $5.00 | $0.75 | about $4.25 per year |
| Lifetime | $15.00 | $1.25 | about $13.75 once |

The price itself lives in Paddle. The app only shows the labels from `monetization_config.json` (`subscription_price_label`, `lifetime_price_label`). If you change a price in Paddle, update the matching label too. No code change is needed.

## 1. Paddle

1. Sign up at [paddle.com](https://www.paddle.com/) and complete seller verification. Paddle reviews your identity and your product, so have ready:
   - a public page describing the app (the GitHub README works)
   - terms, privacy policy and refund policy pages
2. Start in the **sandbox** account at [sandbox-vendors.paddle.com](https://sandbox-vendors.paddle.com/), so you can test without real money.
3. Under **Catalog → Products**, create one product, for example "Battery Tray Monitor – Ad-free", with two prices:
   - **Yearly**: a recurring price of $5.00, billed every year.
   - **Lifetime**: a one-time price of $15.00.
4. Under **Business account → Payouts**, add your Turkish bank account (IBAN + SWIFT) or your Payoneer account.

## 2. RevenueCat

1. Create a project at [app.revenuecat.com](https://app.revenuecat.com/).
2. **Apps & providers → add Paddle Billing**, then connect your Paddle account. Follow RevenueCat's [Paddle integration guide](https://www.revenuecat.com/docs/web/integrations/paddle) for the Paddle API key and checkout settings it asks for. Use the sandbox environment first.
3. **Product catalog → Products**: import both Paddle prices.
4. **Product catalog → Entitlements**: create an entitlement named exactly **`no_ads`** and attach both products to it.
5. **Product catalog → Offerings**: create two offerings, each with one package:
   - `no_ads_subscription`: the yearly product
   - `no_ads_lifetime`: the lifetime product

   Using two offerings means each button in the app opens a checkout for just that plan.
6. **Web → Web Purchase Links**: create one link for each offering, with Paddle as the checkout. Each link looks like `https://pay.rev.cat/<token>`. On the success page, tell buyers they can switch back to the app. The app detects the payment by itself within a few seconds.
7. Copy the **public API key** for the Paddle app, from the app's settings under **Apps & providers**.

The app adds its per-install License ID (its RevenueCat App User ID) to the link, as `https://pay.rev.cat/<token>/<license-id>`. RevenueCat therefore credits the purchase to that install without the user making an account.

## 3. Put the values in the app

You can provide them in either of two ways.

**A. Edit `monetization_config.json`** (fine to commit, because none of these values are secret):

```json
{
  "revenuecat_public_api_key": "<public API key of the Paddle app>",
  "entitlement_id": "no_ads",
  "subscription_purchase_link": "https://pay.rev.cat/<subscription token>",
  "lifetime_purchase_link": "https://pay.rev.cat/<lifetime token>",
  "subscription_price_label": "$5 / year",
  "lifetime_price_label": "$15 one-time"
}
```

The public API key is meant to ship inside apps. It can only read a customer's own entitlements and can't grant anything. **Never** put the RevenueCat *secret* key (`sk_...`) or a Paddle API key in this file.

**B. Use GitHub repository variables**, so nothing is committed. Under *Settings → Secrets and variables → Actions → Variables*, add any of:

- `BTM_REVENUECAT_PUBLIC_API_KEY`
- `BTM_SUBSCRIPTION_PURCHASE_LINK`
- `BTM_LIFETIME_PURCHASE_LINK`
- `BTM_ADS_FEED_URL`

The CI build bakes them into the exe. `Build-Exe.ps1` reads the same names from environment variables for local builds.

If no key or links are set, the app still shows ads, but its purchase buttons are disabled and it says payments aren't set up.

## 4. Test end to end (sandbox)

1. Build with the sandbox public key and sandbox Web Purchase Links.
2. Run the exe, click **Remove ads** (in the popup, or in the tray menu), then **Subscribe** or **Buy once**.
3. Pay on the Paddle sandbox checkout with test card `4242 4242 4242 4242`, any future expiry date, and any CVC.
4. Within a few seconds, the banner disappears and the dialog shows the plan as active.
5. In RevenueCat → **Customers**, search for the License ID shown in the dialog to see the purchase.

When everything works, switch to the production key and links and rebuild.

## Ads

Ads are short text lines with a link, rotated every 20 seconds while the popup is open.

- **House ads** ship inside the exe, in `house_ads` in `monetization_config.json`. The URL `app:remove-ads` opens the purchase dialog instead of a web page.
- **Remote ads**: set `ads_feed_url` to a JSON file you host, such as a GitHub Gist raw URL or GitHub Pages. You can then change or sell ad slots without shipping a new exe. The app re-fetches the feed every 6 hours. Format:

  ```json
  { "ads": [ { "text": "Your ad text (100 chars max)", "url": "https://example.com" } ] }
  ```

  Only `http(s)` links are accepted from the feed. The app ignores entries with any other link type, such as `file:`.

Ad networks such as AdSense and AdMob don't support desktop apps. Direct-sold or house ads through the feed are the practical option for a tray app.

## How the license works (and its limits)

- Each install creates a random License ID (`btm_...`). It's stored in `%APPDATA%\BatteryTrayMonitor\license.json` for the exe, or next to the script when run from source.
- The app checks `GET https://api.revenuecat.com/v1/subscribers/<license-id>` at startup, every 6 hours, and every 4 seconds for 20 minutes after a checkout opens.
- The last confirmed result is cached, so the app stays ad-free offline: a lifetime purchase forever, a subscription until it expires plus 3 days.
- **Moving to a new PC**: the dialog shows the License ID with a **Copy** button. On the new install, use **Restore a purchase...** and paste it.
- **Cancelling or managing a subscription**: the dialog shows a **Manage subscription** button, which opens Paddle's customer portal. Paddle also emails receipts with a manage link.
- The check runs on the user's computer. Someone determined could edit `license.json` to hide the ads. For a cheap ad-removal purchase that's an accepted trade-off. Making it tamper-proof would need your own license server.
