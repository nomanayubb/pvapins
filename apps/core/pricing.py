"""Selling price and PKR conversion. The supplier price is never shown to customers."""
from decimal import ROUND_UP, Decimal

import requests
from django.core.cache import cache

from .models import SiteSetting

CENT = Decimal("0.01")
RATE_CACHE_KEY = "usd_pkr_live_rate"
RATE_TTL = 6 * 3600


def sell_price(cost, setting=None):
    """cost + markup, never less than cost + min margin, rounded UP to the cent."""
    setting = setting or SiteSetting.get()
    cost = Decimal(str(cost))
    by_percent = cost * (Decimal(1) + setting.markup_percent / Decimal(100))
    by_margin = cost + setting.min_margin_usd
    return max(by_percent, by_margin).quantize(CENT, rounding=ROUND_UP)


def _live_rate():
    rate = cache.get(RATE_CACHE_KEY)
    if rate:
        return Decimal(str(rate))
    try:
        r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=5)
        rate = r.json()["rates"]["PKR"]
        if rate and float(rate) > 0:
            cache.set(RATE_CACHE_KEY, rate, RATE_TTL)
            return Decimal(str(rate))
    except Exception:
        pass
    return None


def usd_to_pkr(setting=None):
    setting = setting or SiteSetting.get()
    if setting.auto_pkr_rate:
        live = _live_rate()
        if live:
            return live
    return setting.usd_to_pkr


def to_pkr(usd, setting=None):
    return (Decimal(str(usd)) * usd_to_pkr(setting)).quantize(CENT)
