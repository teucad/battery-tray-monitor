"""Tk widgets for monetization: the small ad banner at the bottom of the
battery popup, and the "Remove ads" purchase/license dialog. All state lives
in monetization.py; these only render it, and must only be touched from the
Tk thread."""

import tkinter as tk
from tkinter import simpledialog

import monetization

BG = "#1e1e1e"
CARD_BG = "#262626"
BORDER = "#3a3a3a"
FG = "#eeeeee"
FG_DIM = "#aaaaaa"
FG_FAINT = "#777777"
ACCENT = "#4a90d9"
ACCENT_ACTIVE = "#3a7bc8"
SUCCESS = "#28a745"
ERROR = "#e5534b"

AD_ROTATE_MS = 20_000
# How long "Checking..." stays up before falling back to whatever the
# license manager reports - its own change notification usually re-renders
# sooner than this.
CHECKING_MESSAGE_MS = 4000


def _link(parent, text, command, fg=ACCENT, **kwargs):
    label = tk.Label(parent, text=text, fg=fg, bg=parent["bg"], cursor="hand2", **kwargs)
    label.bind("<Button-1>", lambda e: command())
    return label


def _button(parent, text, command, primary=True):
    return tk.Button(
        parent, text=text, command=command, relief="flat", bd=0, padx=12, pady=4,
        cursor="hand2", highlightthickness=0,
        bg=ACCENT if primary else "#3a3a3a", fg="#ffffff",
        activebackground=ACCENT_ACTIVE if primary else "#4a4a4a", activeforeground="#ffffff",
    )


class AdBanner(tk.Frame):
    """One-line-ish text ad under the device list, with a "Remove ads"
    link. Rotates to the next ad every AD_ROTATE_MS while running."""

    def __init__(self, parent, ad_provider, on_remove_ads):
        super().__init__(parent, bg=BG)
        self.ad_provider = ad_provider
        self.on_remove_ads = on_remove_ads
        self._ad = None
        self._after_id = None

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", pady=(8, 6))

        header = tk.Frame(self, bg=BG)
        header.pack(fill="x")
        tk.Label(
            header, text="AD", font=("Segoe UI", 7, "bold"), fg=BG, bg=FG_FAINT, padx=3,
        ).pack(side="left")
        _link(header, "Remove ads", on_remove_ads, font=("Segoe UI", 8, "underline")).pack(side="right")

        self.text_label = tk.Label(
            self, text="", fg=FG_DIM, bg=BG, anchor="w", justify="left", cursor="hand2",
        )
        self.text_label.pack(fill="x", pady=(4, 0))
        self.text_label.bind("<Button-1>", lambda e: self._click())

    def set_wraplength(self, pixels):
        self.text_label.configure(wraplength=max(120, pixels))

    def _click(self):
        if not self._ad:
            return
        if self._ad["url"] == monetization.REMOVE_ADS_URL:
            self.on_remove_ads()
        else:
            monetization.open_ad(self._ad)

    def rotate(self):
        self._ad = self.ad_provider.next_ad()
        self.text_label.configure(text=self._ad["text"])

    def start(self):
        self.stop()
        self.rotate()
        self._schedule()

    def _schedule(self):
        def tick():
            self.rotate()
            self._schedule()

        self._after_id = self.after(AD_ROTATE_MS, tick)

    def stop(self):
        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None


class RemoveAdsDialog:
    """Purchase dialog: the two plans, payment-confirmation status, and the
    License ID (this install's RevenueCat App User ID) for restoring a
    purchase on another PC. A single instance is reused; open() raises it."""

    def __init__(self, root, license_manager):
        self.root = root
        self.license = license_manager
        self.config = license_manager.config
        self.window = None
        self._message = None  # (text, color) from the last button press

    def open(self):
        if self.window is not None and self.window.winfo_exists():
            self.window.deiconify()
            self.window.lift()
            self.window.focus_force()
            return
        self._message = None
        self.window = tk.Toplevel(self.root, bg=BG, padx=18, pady=16)
        self.window.title("Remove ads - Battery Tray Monitor")
        self.window.resizable(False, False)
        self.window.attributes("-topmost", True)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Escape>", lambda e: self.close())

        tk.Label(
            self.window, text="Remove ads", font=("Segoe UI", 13, "bold"), fg=FG, bg=BG, anchor="w",
        ).pack(fill="x")
        tk.Label(
            self.window, text="Hide the ad banner and support Battery Tray Monitor.",
            fg=FG_DIM, bg=BG, anchor="w",
        ).pack(fill="x", pady=(2, 12))

        self.body = tk.Frame(self.window, bg=BG)
        self.body.pack(fill="x")
        self.license_frame = tk.Frame(self.window, bg=BG)
        self.license_frame.pack(fill="x")

        self.refresh()
        self.license.refresh_async()

        self.window.update_idletasks()
        w, h = self.window.winfo_reqwidth(), self.window.winfo_reqheight()
        x = (self.window.winfo_screenwidth() - w) // 2
        y = (self.window.winfo_screenheight() - h) // 3
        self.window.geometry(f"+{x}+{y}")
        self.window.focus_force()

    def close(self):
        if self.window is not None:
            self.window.destroy()
            self.window = None

    def refresh(self):
        """Re-renders from the license manager's current status; called on
        open and whenever the license manager reports a change."""
        if self.window is None or not self.window.winfo_exists():
            return
        for frame in (self.body, self.license_frame):
            for child in frame.winfo_children():
                child.destroy()

        status = self.license.status()
        if status["ad_free"]:
            self._render_owned(status)
        else:
            self._render_plans(status)
        self._render_status(status)
        self._render_license()

    def _render_owned(self, status):
        if status["lifetime"]:
            text = "✓ Ads removed for good - thanks for your support!"
        else:
            expires = status["expires"].astimezone().strftime("%d %b %Y") if status["expires"] else "?"
            text = f"✓ Ad-free subscription active (renews or ends {expires})."
        tk.Label(
            self.body, text=text, fg=SUCCESS, bg=BG, anchor="w", justify="left", wraplength=390,
        ).pack(fill="x", pady=(0, 6))
        if not status["lifetime"] and status["management_url"]:
            url = status["management_url"]
            _button(
                self.body, "Manage subscription",
                lambda: monetization.open_ad({"url": url}), primary=False,
            ).pack(anchor="w", pady=(0, 6))

    def _render_plans(self, status):
        plans = [
            (monetization.PLAN_SUBSCRIPTION, "Yearly", self.config.subscription_price_label,
             "Renews yearly. Cancel anytime.", "Subscribe"),
            (monetization.PLAN_LIFETIME, "Lifetime", self.config.lifetime_price_label,
             "Pay once, ad-free forever.", "Buy once"),
        ]
        for plan, name, price, blurb, action in plans:
            if not self.config.purchase_link(plan) and self.config.payments_configured:
                continue  # only one of the two plans set up - hide the other
            card = tk.Frame(
                self.body, bg=CARD_BG, padx=12, pady=10,
                highlightthickness=1, highlightbackground=BORDER,
            )
            card.pack(fill="x", pady=(0, 8))
            text = tk.Frame(card, bg=CARD_BG)
            text.pack(side="left", fill="x", expand=True)
            tk.Label(text, text=name, font=("Segoe UI", 10, "bold"), fg=FG, bg=CARD_BG, anchor="w").pack(fill="x")
            tk.Label(text, text=price, fg=FG, bg=CARD_BG, anchor="w").pack(fill="x")
            tk.Label(text, text=blurb, fg=FG_FAINT, bg=CARD_BG, anchor="w").pack(fill="x")
            button = _button(card, action, lambda p=plan: self._buy(p))
            button.pack(side="right", padx=(12, 0))
            if not self.config.payments_configured:
                button.configure(state="disabled", bg="#3a3a3a", cursor="arrow")

        tk.Label(
            self.body, text="Secure checkout by Paddle opens in your browser. Prices may include local VAT.",
            fg=FG_FAINT, bg=BG, anchor="w", justify="left", wraplength=390,
        ).pack(fill="x", pady=(0, 6))

        if status["had_entitlement"]:
            tk.Label(
                self.body, text="Your ad-free subscription has ended.",
                fg=FG_DIM, bg=BG, anchor="w",
            ).pack(fill="x")

    def _render_status(self, status):
        row = tk.Frame(self.body, bg=BG)
        row.pack(fill="x", pady=(2, 4))
        if not self.config.payments_configured:
            text, color = "Payments aren't set up in this build yet.", FG_DIM
        elif status["ad_free"]:
            text, color = "", FG_DIM
        elif status["waiting_for_payment"]:
            text, color = "Waiting for payment confirmation... finish checkout in your browser.", FG_DIM
        elif self._message:
            text, color = self._message
        elif status["last_error"]:
            text, color = status["last_error"], ERROR
        else:
            text, color = "", FG_DIM
        if text:
            tk.Label(row, text=text, fg=color, bg=BG, anchor="w", justify="left", wraplength=390).pack(fill="x")
        if self.config.payments_configured and not status["ad_free"]:
            _link(row, "Already paid? Check again", self._check).pack(anchor="w", pady=(2, 0))

    def _render_license(self):
        tk.Frame(self.license_frame, bg=BORDER, height=1).pack(fill="x", pady=(8, 8))
        tk.Label(
            self.license_frame, text="License ID (keep this to restore your purchase on another PC):",
            fg=FG_FAINT, bg=BG, anchor="w", justify="left", wraplength=390,
        ).pack(fill="x")
        row = tk.Frame(self.license_frame, bg=BG)
        row.pack(fill="x", pady=(4, 0))
        value = tk.StringVar(value=self.license.app_user_id)
        entry = tk.Entry(
            row, textvariable=value, state="readonly", relief="flat",
            readonlybackground=CARD_BG, fg=FG, width=38,
        )
        entry.pack(side="left", fill="x", expand=True, ipady=3)
        _button(row, "Copy", self._copy_license_id, primary=False).pack(side="left", padx=(6, 0))

        actions = tk.Frame(self.license_frame, bg=BG)
        actions.pack(fill="x", pady=(10, 0))
        _link(actions, "Restore a purchase...", self._restore).pack(side="left")
        _button(actions, "Close", self.close, primary=False).pack(side="right")

    def _buy(self, plan):
        error = self.license.start_purchase(plan)
        self._message = (error, ERROR) if error else None
        self.refresh()

    def _check(self):
        self._message = ("Checking...", FG_DIM)
        self.refresh()
        self.license.refresh_async()

        def clear():
            if self._message and self._message[0] == "Checking...":
                self._message = None
                self.refresh()

        self.window.after(CHECKING_MESSAGE_MS, clear)

    def _copy_license_id(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.license.app_user_id)
        self._message = ("License ID copied.", FG_DIM)
        self.refresh()

    def _restore(self):
        new_id = simpledialog.askstring(
            "Restore purchase",
            "Paste the License ID from the install you bought on:",
            parent=self.window,
        )
        if new_id is None:
            return
        error = self.license.restore(new_id)
        self._message = (error, ERROR) if error else ("License ID updated - checking...", FG_DIM)
        self.refresh()

