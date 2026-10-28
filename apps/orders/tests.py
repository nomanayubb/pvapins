from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core import pvapins
from apps.core.models import SiteSetting
from apps.wallet import services as wallet

from . import services
from .models import Order

COUNTRIES = [{"id": 58, "name": "USA"}]
APPS = [{"id": 1, "name": "Telegram", "trending": True, "cost": Decimal("0.12")}]


class OrderFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        SiteSetting.objects.update_or_create(pk=1, defaults={"auto_pkr_rate": False})
        self.user = get_user_model().objects.create_user("dan", "dan@example.com", "pw-12345-x")
        wallet.adjust(self.user, Decimal("5.00"), "topup", "seed")
        for target, rv in (("countries", COUNTRIES), ("apps", APPS)):
            p = mock.patch.object(pvapins, target, return_value=rv)
            p.start()
            self.addCleanup(p.stop)

    def balance(self):
        self.user.wallet.refresh_from_db()
        return self.user.wallet.balance

    def place(self):
        with mock.patch.object(pvapins, "get_number", return_value="12025550123") as gn:
            return services.place_order(self.user, 58, 1), gn

    def test_buy_charges_marked_up_price(self):
        order, gn = self.place()
        self.assertEqual(order.price, Decimal("0.24"))
        self.assertEqual(order.cost, Decimal("0.12"))
        self.assertEqual(self.balance(), Decimal("4.76"))
        gn.assert_called_once_with("Telegram", "USA")

    def test_supplier_failure_refunds_immediately(self):
        with mock.patch.object(pvapins, "get_number", side_effect=pvapins.SupplierError("No Number Found")):
            with self.assertRaises(services.OrderError):
                services.place_order(self.user, 58, 1)
        self.assertEqual(self.balance(), Decimal("5.00"))
        self.assertFalse(Order.objects.exists())

    def test_insufficient_balance_never_calls_supplier(self):
        wallet.debit(self.user, Decimal("4.90"))
        with mock.patch.object(pvapins, "get_number") as gn:
            with self.assertRaisesMessage(services.OrderError, "insufficient"):
                services.place_order(self.user, 58, 1)
        gn.assert_not_called()

    def test_unknown_product_rejected(self):
        with self.assertRaises(services.OrderError):
            services.place_order(self.user, 58, 999)
        self.assertEqual(self.balance(), Decimal("5.00"))

    def test_otp_arrives(self):
        order, _ = self.place()
        with mock.patch.object(pvapins, "get_sms", return_value=pvapins.SmsResult("received", "418494", "Code 418494")):
            order = services.refresh(order)
        self.assertEqual((order.status, order.otp), (Order.COMPLETED, "418494"))
        self.assertEqual(self.balance(), Decimal("4.76"))  # charged, not refunded

    def test_reject_refunds_once(self):
        order, _ = self.place()
        with mock.patch.object(pvapins, "get_sms", return_value=pvapins.SmsResult("pending")), \
             mock.patch.object(pvapins, "reject_number", return_value=True):
            services.reject(order)
            self.assertEqual(self.balance(), Decimal("5.00"))
            with self.assertRaises(services.OrderError):
                services.reject(Order.objects.get(pk=order.pk))
        self.assertEqual(self.balance(), Decimal("5.00"))

    def test_reject_not_confirmed_keeps_charge(self):
        order, _ = self.place()
        with mock.patch.object(pvapins, "get_sms", return_value=pvapins.SmsResult("pending")), \
             mock.patch.object(pvapins, "reject_number", return_value=False):
            with self.assertRaises(services.OrderError):
                services.reject(order)
        self.assertEqual(self.balance(), Decimal("4.76"))

    def test_cannot_reject_after_code(self):
        order, _ = self.place()
        with mock.patch.object(pvapins, "get_sms", return_value=pvapins.SmsResult("received", "111111", "111111")), \
             mock.patch.object(pvapins, "reject_number", return_value=True) as rj:
            with self.assertRaises(services.OrderError):
                services.reject(order)
        rj.assert_not_called()
        self.assertEqual(self.balance(), Decimal("4.76"))

    def test_expiry_auto_refunds_once(self):
        order, _ = self.place()
        Order.objects.filter(pk=order.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        order = services.refresh(Order.objects.get(pk=order.pk))
        services.refresh(Order.objects.get(pk=order.pk))
        self.assertEqual(order.status, Order.EXPIRED)
        self.assertEqual(self.balance(), Decimal("5.00"))

    def test_reuse_is_free_and_time_limited(self):
        order, _ = self.place()
        with mock.patch.object(pvapins, "get_number", return_value="12025550123") as gn:
            again = services.reuse_order(self.user, order)
        self.assertEqual(again.price, 0)
        self.assertEqual(self.balance(), Decimal("4.76"))
        gn.assert_called_once_with("Telegram", "USA", reuse_number="12025550123")
        Order.objects.filter(pk=order.pk).update(created=timezone.now() - timedelta(minutes=16))
        with self.assertRaises(services.OrderError):
            services.reuse_order(self.user, Order.objects.get(pk=order.pk))

    def test_rent_flow(self):
        with mock.patch.object(pvapins, "rent_number", return_value="12817437990"), \
             mock.patch.object(pvapins, "rent_list", return_value=[{"number": "12817437990", "expiry": "2030-01-01 00:00:00"}]):
            order = services.place_order(self.user, 58, 1, rent=True)
        self.assertEqual(order.kind, Order.RENT)
        self.assertIsNotNone(order.expires_at)
        msgs = [{"from": "22000", "message": "Use code 418494 only", "timestamp": "t"}]
        with mock.patch.object(pvapins, "rent_messages", return_value=msgs):
            order = services.refresh(order)
        self.assertEqual(order.otp, "418494")
        # released after receiving an SMS: no refund
        with mock.patch.object(pvapins, "rent_reject"), mock.patch.object(pvapins, "rent_messages", return_value=msgs):
            services.reject(order)
        self.assertEqual(self.balance(), Decimal("4.76"))

    def test_other_users_order_is_404(self):
        order, _ = self.place()
        other = get_user_model().objects.create_user("eve", "eve@example.com", "pw-12345-x")
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("order_detail", args=[order.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("order_status", args=[order.pk])).status_code, 404)

    def test_status_json_hides_supplier_and_shows_price(self):
        order, _ = self.place()
        self.client.force_login(self.user)
        with mock.patch.object(pvapins, "get_sms", return_value=pvapins.SmsResult("pending")):
            resp = self.client.get(reverse("order_status", args=[order.pk]))
        self.assertNotIn("pvapins", resp.content.decode().lower())
        self.assertEqual(resp.json()["status"], "active")
        page = self.client.get(reverse("dashboard")).content.decode()
        self.assertNotIn("pvapins", page.lower())
        self.assertIn("$0.24", page)

    def test_buy_view_end_to_end(self):
        self.client.force_login(self.user)
        with mock.patch.object(pvapins, "get_number", return_value="12025550123"):
            resp = self.client.post(reverse("place_order"), {"country": 58, "app": 1})
        order = Order.objects.get()
        self.assertRedirects(resp, reverse("order_detail", args=[order.pk]), fetch_redirect_response=False)
