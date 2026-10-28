"""Thin client for the PVAPins classic API (https://api.pvapins.com/user/api/).

The classic API is used because its catalogue (country names, app names, prices)
maps 1:1 onto get_number / get_sms / reject. The key travels server-side only.
Response parsing is deliberately tolerant: the docs list error strings but not the
exact success body of get_number / get_sms, so both JSON and plain text are handled.
"""
import json
import re
from dataclasses import dataclass
from decimal import Decimal

import requests
from django.conf import settings
from django.core.cache import cache

CATALOG_TTL = 600


_SUPPLIER_NAME = re.compile(r"(https?://)?(api\.)?pv\s*a\s*pins(\.com)?", re.IGNORECASE)


def clean(text):
    """Customers must never see the upstream provider's name or URL."""
    return _SUPPLIER_NAME.sub("our provider", str(text))[:200]


class SupplierError(Exception):
    def __init__(self, message, retryable=False):
        message = clean(message)
        super().__init__(message)
        self.message = message
        self.retryable = retryable


@dataclass
class SmsResult:
    status: str  # "pending" | "received" | "error"
    code: str = ""
    message: str = ""


def _request(path, params=None, auth=False, timeout=30):
    params = dict(params or {})
    if auth:
        if not settings.PVAPINS_API_KEY:
            raise SupplierError("Service is not configured yet.")
        params["customer"] = settings.PVAPINS_API_KEY
    try:
        resp = requests.get(f"{settings.PVAPINS_BASE_URL}/{path}", params=params, timeout=timeout)
    except requests.RequestException:
        raise SupplierError("Service temporarily unavailable. Please try again.", retryable=True)
    if resp.status_code >= 500:
        raise SupplierError("Service temporarily unavailable. Please try again.", retryable=True)
    return resp.text.strip()


def _json(text):
    try:
        return json.loads(text)
    except ValueError:
        return None


def _error_text(data, text):
    if isinstance(data, dict):
        for key in ("error", "message", "data"):
            if isinstance(data.get(key), str):
                return data[key]
    return text


# --- catalogue (no auth, cached) ---------------------------------------

def countries(rent=False):
    key = f"pv_countries_{int(rent)}"
    data = cache.get(key)
    if data is None:
        text = _request("load_countries.php", {"is_rent": 1} if rent else None)
        data = _json(text)
        if not isinstance(data, list):
            raise SupplierError("Could not load countries.", retryable=True)
        data = [{"id": int(c["id"]), "name": c["full_name"]} for c in data]
        cache.set(key, data, CATALOG_TTL)
    return data


def apps(country_id, rent=False):
    """Products for a country, in the supplier's own order."""
    key = f"pv_apps_{int(country_id)}_{int(rent)}"
    data = cache.get(key)
    if data is None:
        params = {"country_id": int(country_id)}
        if rent:
            params["is_rent"] = 1
        data = _json(_request("load_apps.php", params, timeout=60))
        if not isinstance(data, list):
            raise SupplierError("Could not load products.", retryable=True)
        data = [
            {
                "id": int(a["id"]),
                "name": a["full_name"],
                "trending": bool(int(a.get("trending") or 0)),
                "cost": Decimal(str(a.get("deduct") or "0")),
            }
            for a in data
        ]
        cache.set(key, data, CATALOG_TTL)
    return data


def country_by_id(country_id, rent=False):
    return next((c for c in countries(rent) if c["id"] == int(country_id)), None)


def app_by_id(country_id, app_id, rent=False):
    return next((a for a in apps(country_id, rent) if a["id"] == int(app_id)), None)


# --- parsing -----------------------------------------------------------

_PHONE = re.compile(r"^\+?\d{6,16}$")
_OTP = re.compile(r"(?<!\d)(\d{4,8})(?!\d)")


def parse_number(text):
    data = _json(text)
    if isinstance(data, dict):
        code = data.get("code")
        if data.get("error") or code == 200:
            raise SupplierError(_error_text(data, text))
        for key in ("number", "phone", "phone_number", "data"):
            value = data.get(key)
            if value is not None and _PHONE.match(str(value).strip()):
                return str(value).strip().lstrip("+")
        raise SupplierError(_error_text(data, text) or "Unexpected supplier response.")
    plain = text.strip().strip('"')
    if _PHONE.match(plain):
        return plain.lstrip("+")
    raise SupplierError(plain or "Empty supplier response.", retryable="registration in progress" in plain.lower())


def parse_sms(text):
    data = _json(text)
    lowered = text.lower()
    if "not received any code" in lowered:
        return SmsResult("pending")
    if isinstance(data, dict):
        if data.get("error"):
            return SmsResult("error", message=str(data["error"]))
        for key in ("code", "otp", "sms", "message", "data"):
            value = data.get(key)
            if value:
                return _sms_from_message(str(value))
        return SmsResult("pending")
    if isinstance(data, list):
        if not data:
            return SmsResult("pending")
        first = data[0]
        value = first.get("message") if isinstance(first, dict) else first
        return _sms_from_message(str(value))
    if any(s in lowered for s in ("not found", "error 102", "balance is expired")):
        return SmsResult("error", message=text.strip())
    return _sms_from_message(text.strip().strip('"'))


def _sms_from_message(message):
    match = _OTP.search(message)
    return SmsResult("received", code=match.group(1) if match else message[:64], message=message)


# --- temporary numbers (auth) ------------------------------------------

def _pair(app_name, operator):
    return {"app": app_name, **({"operator": operator} if operator else {})}


def get_number(app_name, country_name, operator=None, reuse_number=None):
    params = {"country": country_name, **_pair(app_name, operator)}
    if reuse_number:
        params["number"] = reuse_number
    return parse_number(_request("get_number.php", params, auth=True))


def get_sms(number, app_name, country_name, operator=None):
    params = {"number": number, "country": country_name, **_pair(app_name, operator)}
    return parse_sms(_request("get_sms.php", params, auth=True))


def reject_number(number, app_name, country_name, operator=None):
    """Returns True only when the supplier confirms the number was rejected."""
    params = {"number": number, "country": country_name, **_pair(app_name, operator)}
    text = _request("get_reject_number.php", params, auth=True).lower()
    return "number rejected" in text or text.strip(' ."') == "rejected"


def balance():
    return _json(_request("get_balance.php", auth=True)) or {}


# --- rent (auth) -------------------------------------------------------

def _rent_json(path, params):
    data = _json(_request(path, params, auth=True))
    if not isinstance(data, dict):
        raise SupplierError("Unexpected supplier response.")
    if data.get("code") != 100:
        raise SupplierError(str(data.get("data") or data.get("error") or "Supplier refused the request."))
    return data


def rent_number(app_name, country_name):
    data = _rent_json("rent.php", {"app": app_name, "country": country_name})
    return str(data["data"]).strip().lstrip("+")


def rent_list():
    data = _json(_request("load_rent.php", auth=True))
    return data if isinstance(data, list) else []


def rent_messages(number, app_name, country_name):
    data = _json(_request("load_rent_code.php", {"number": number, "app": app_name, "country": country_name}, auth=True))
    return data if isinstance(data, list) else []


def rent_renew(number, app_name, country_name):
    _rent_json("rent_renew_number.php", {"number": number, "app": app_name, "country": country_name})


def rent_reject(number, app_name, country_name):
    _rent_json("reject_rent.php", {"number": number, "app": app_name, "country": country_name})
