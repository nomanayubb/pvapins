"""NOWPayments hosted-invoice flow.

1. We create an invoice for a USD amount and send the user to invoice_url.
2. NOWPayments POSTs an IPN to /wallet/ipn/ signed with HMAC-SHA512 of the
   key-sorted JSON body, using the IPN secret. Only a verified IPN is trusted.
"""
import hashlib
import hmac
import json
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings


class NowPaymentsError(Exception):
    pass


def _base():
    return "https://api-sandbox.nowpayments.io/v1" if settings.NOWPAYMENTS_SANDBOX else "https://api.nowpayments.io/v1"


def create_invoice(deposit):
    if not settings.NOWPAYMENTS_API_KEY:
        raise NowPaymentsError("Crypto payments are not configured yet.")
    payload = {
        "price_amount": float(deposit.usd_amount),
        "price_currency": "usd",
        "order_id": deposit.order_id,
        "order_description": f"{settings.SITE_NAME} wallet top-up",
        "ipn_callback_url": f"{settings.SITE_URL}/wallet/ipn/",
        "success_url": f"{settings.SITE_URL}/wallet/?paid=1",
        "cancel_url": f"{settings.SITE_URL}/wallet/",
    }
    try:
        resp = requests.post(
            f"{_base()}/invoice", json=payload, timeout=20,
            headers={"x-api-key": settings.NOWPAYMENTS_API_KEY, "Content-Type": "application/json"},
        )
        data = resp.json()
    except (requests.RequestException, ValueError):
        raise NowPaymentsError("Could not reach the payment provider. Try again.")
    if resp.status_code >= 400 or "invoice_url" not in data:
        raise NowPaymentsError(data.get("message") or "Payment provider rejected the request.")
    return data


def signature_for(payload):
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    return hmac.new(settings.NOWPAYMENTS_IPN_SECRET.encode(), body.encode(), hashlib.sha512).hexdigest()


def verify_ipn(payload, header_sig):
    if not settings.NOWPAYMENTS_IPN_SECRET or not header_sig:
        return False
    return hmac.compare_digest(signature_for(payload), header_sig.strip().lower())


def same_amount(a, b):
    try:
        return abs(Decimal(str(a)) - Decimal(str(b))) <= Decimal("0.01")
    except (InvalidOperation, TypeError):
        return False
