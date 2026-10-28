from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from . import pvapins
from .models import SiteSetting
from .pricing import sell_price, to_pkr

CATALOG_COUNTRIES = [{"id": 58, "name": "USA"}, {"id": 62, "name": "UK"}]
CATALOG_APPS = [
    {"id": 1, "name": "Telegram", "trending": True, "cost": Decimal("0.12")},
    {"id": 2, "name": "Facebook40", "trending": False, "cost": Decimal("0.91")},
]


def fake_catalog():
    return (
        mock.patch.object(pvapins, "countries", return_value=CATALOG_COUNTRIES),
        mock.patch.object(pvapins, "apps", return_value=CATALOG_APPS),
    )


class PricingTests(TestCase):
    def setUp(self):
        cache.clear()
        SiteSetting.objects.update_or_create(pk=1, defaults={"auto_pkr_rate": False, "usd_to_pkr": Decimal("280")})

    def test_default_markup_doubles_price(self):
        self.assertEqual(sell_price("0.12"), Decimal("0.24"))
        self.assertEqual(sell_price("0.91"), Decimal("1.82"))

    def test_minimum_margin_on_tiny_prices(self):
        self.assertEqual(sell_price("0.01"), Decimal("0.06"))

    def test_rounds_up_to_cent(self):
        SiteSetting.objects.filter(pk=1).update(markup_percent=Decimal("33"))
        cache.clear()
        self.assertEqual(sell_price("0.15"), Decimal("0.20"))  # 0.1995 -> 0.20

    def test_pkr_conversion(self):
        self.assertEqual(to_pkr("0.24"), Decimal("67.20"))


class ParserTests(TestCase):
    def test_number_plain_and_json(self):
        self.assertEqual(pvapins.parse_number("60123456789"), "60123456789")
        self.assertEqual(pvapins.parse_number("+60123456789"), "60123456789")
        self.assertEqual(pvapins.parse_number('{"number":"60123456789"}'), "60123456789")
        self.assertEqual(pvapins.parse_number('{"data":"112869555","code":100}'), "112869555")

    def test_number_errors(self):
        for text in ("Customer Not Found.", "App Not Found.", "Error 102, check back later.", '{"error":"Customer Not Found."}',
                     '{"data":"Currently, The number is unavailable","code":200}'):
            with self.assertRaises(pvapins.SupplierError):
                pvapins.parse_number(text)

    def test_registration_in_progress_is_retryable(self):
        with self.assertRaises(pvapins.SupplierError) as ctx:
            pvapins.parse_number("New Numbers registration in progress, please wait or check back later.")
        self.assertTrue(ctx.exception.retryable)

    def test_sms_states(self):
        self.assertEqual(pvapins.parse_sms("You have not received any code yet.").status, "pending")
        self.assertEqual(pvapins.parse_sms("Customer Not Found.").status, "error")
        r = pvapins.parse_sms("Your Telegram code: 418494. Do not share")
        self.assertEqual((r.status, r.code), ("received", "418494"))
        r = pvapins.parse_sms('[{"from":"22000","message":"Use code 123456 to sign up","timestamp":"x"}]')
        self.assertEqual((r.status, r.code), ("received", "123456"))
        self.assertEqual(pvapins.parse_sms("[]").status, "pending")

    def test_supplier_name_is_scrubbed(self):
        err = pvapins.SupplierError("Request to https://api.pvapins.com/user/api/x failed at PVAPins")
        self.assertNotIn("pvapins", err.message.lower())


class PageTests(TestCase):
    def setUp(self):
        cache.clear()
        SiteSetting.objects.update_or_create(pk=1, defaults={"auto_pkr_rate": False})

    def test_catalog_shows_usd_and_pkr_and_hides_supplier(self):
        c, a = fake_catalog()
        with c, a:
            for name in ("home", "buy", "rent", "countries", "pricing", "faq", "contact"):
                resp = self.client.get(reverse(name))
                self.assertEqual(resp.status_code, 200, name)
                self.assertNotIn("pvapins", resp.content.decode().lower(), name)
            body = self.client.get(reverse("buy"), {"country": 58}).content.decode()
            self.assertIn("$0.24", body)
            self.assertIn("Rs 67.20", body)
            self.assertNotIn("$0.12", body)  # supplier cost never leaks
            self.assertNotIn("$0.91", body)

    def test_buy_requires_login(self):
        resp = self.client.post(reverse("place_order"), {"country": 58, "app": 1})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login/", resp["Location"])
