import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from . import nowpayments, services
from .models import Deposit, Transaction

SECRET = "test-ipn-secret"


@override_settings(NOWPAYMENTS_IPN_SECRET=SECRET)
class IpnTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("bob", "bob@example.com", "pw-12345-x")
        self.deposit = Deposit.objects.create(user=self.user, usd_amount=Decimal("10.00"))

    def post(self, payload, sig=None):
        sig = nowpayments.signature_for(payload) if sig is None else sig
        return self.client.post(reverse("ipn"), data=json.dumps(payload), content_type="application/json",
                                HTTP_X_NOWPAYMENTS_SIG=sig)

    def payload(self, **kw):
        base = {"payment_id": 5, "payment_status": "finished", "pay_currency": "usdttrc20", "price_amount": 10,
                "price_currency": "usd", "order_id": self.deposit.order_id, "actually_paid": 10.2}
        base.update(kw)
        return base

    def balance(self):
        self.user.wallet.refresh_from_db()
        return self.user.wallet.balance

    def test_bad_signature_rejected(self):
        resp = self.post(self.payload(), sig="deadbeef")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(self.balance(), 0)

    def test_missing_signature_rejected(self):
        resp = self.client.post(reverse("ipn"), data=json.dumps(self.payload()), content_type="application/json")
        self.assertEqual(resp.status_code, 401)

    def test_finished_credits_once(self):
        self.assertEqual(self.post(self.payload()).status_code, 200)
        self.assertEqual(self.balance(), Decimal("10.00"))
        self.post(self.payload())  # NOWPayments retries
        self.assertEqual(self.balance(), Decimal("10.00"))
        self.assertEqual(Transaction.objects.filter(kind="topup").count(), 1)

    def test_waiting_does_not_credit(self):
        self.post(self.payload(payment_status="waiting"))
        self.assertEqual(self.balance(), 0)
        self.deposit.refresh_from_db()
        self.assertEqual(self.deposit.status, "waiting")

    def test_amount_mismatch_not_credited(self):
        self.post(self.payload(price_amount=1))
        self.assertEqual(self.balance(), 0)

    def test_credit_uses_our_amount_not_payload_extras(self):
        self.post(self.payload(actually_paid=9999))
        self.assertEqual(self.balance(), Decimal("10.00"))

    @override_settings(NOWPAYMENTS_IPN_SECRET="")
    def test_no_secret_configured_rejects_everything(self):
        self.assertEqual(self.post(self.payload(), sig="x").status_code, 401)


class LedgerTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("amy", "amy@example.com", "pw-12345-x")

    def test_wallet_created_on_signup(self):
        self.assertEqual(self.user.wallet.balance, 0)

    def test_cannot_overdraw(self):
        with self.assertRaises(services.InsufficientFunds):
            services.debit(self.user, Decimal("0.01"))

    def test_refund_reference_is_idempotent(self):
        services.adjust(self.user, Decimal("5"), "topup", "d1")
        services.refund(self.user, Decimal("1"), reference="order-1")
        self.assertIsNone(services.refund(self.user, Decimal("1"), reference="order-1"))
        self.user.wallet.refresh_from_db()
        self.assertEqual(self.user.wallet.balance, Decimal("6"))


class DepositViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("cat", "cat@example.com", "pw-12345-x")
        self.client.force_login(self.user)

    def test_rejects_below_minimum(self):
        self.client.post(reverse("deposit"), {"amount": "0.50"})
        self.assertEqual(Deposit.objects.count(), 0)

    def test_without_api_key_marks_failed_and_does_not_crash(self):
        resp = self.client.post(reverse("deposit"), {"amount": "10"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Deposit.objects.get().status, "failed")
