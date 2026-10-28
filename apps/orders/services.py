"""Order lifecycle. Money rule: debit first, then call the supplier; any failure refunds.

Prices always come from the server-side catalogue - the client only sends ids.
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.core import pvapins
from apps.core.models import SiteSetting
from apps.core.pricing import sell_price
from apps.wallet import services as wallet

from .models import Order

POLL_MIN_INTERVAL = timedelta(seconds=3)
REUSE_WINDOW = timedelta(minutes=15)


class OrderError(Exception):
    pass


def _resolve(country_id, app_id, rent):
    try:
        country = pvapins.country_by_id(country_id, rent)
        app = pvapins.app_by_id(country_id, app_id, rent) if country else None
    except pvapins.SupplierError as exc:
        raise OrderError(exc.message)
    if not country or not app:
        raise OrderError("That product is no longer available.")
    if app["cost"] <= 0:
        raise OrderError("That product has no price right now.")
    return country, app


def _charge(user, price, label):
    try:
        wallet.debit(user, price, note=label)
    except wallet.InsufficientFunds:
        raise OrderError("insufficient")


def place_order(user, country_id, app_id, rent=False):
    country, app = _resolve(country_id, app_id, rent)
    price = sell_price(app["cost"])
    label = f"{'Rent' if rent else 'Number'}: {app['name']} / {country['name']}"
    _charge(user, price, label)
    try:
        if rent:
            number = pvapins.rent_number(app["name"], country["name"])
        else:
            number = pvapins.get_number(app["name"], country["name"])
    except pvapins.SupplierError as exc:
        wallet.adjust(user, price, "refund", note=f"Refund (no number): {label}")
        raise OrderError(exc.message)

    minutes = SiteSetting.get().temp_number_minutes
    order = Order.objects.create(
        user=user, kind=Order.RENT if rent else Order.TEMP,
        country_id=country["id"], country_name=country["name"], app_id=app["id"], app_name=app["name"],
        number=number, price=price, cost=app["cost"],
        expires_at=None if rent else timezone.now() + timedelta(minutes=minutes),
    )
    if rent:
        _sync_rent_expiry(order)
    return order


def can_reuse(order):
    return (
        order.kind == Order.TEMP and not order.refunded and order.status in (Order.ACTIVE, Order.COMPLETED)
        and timezone.now() - order.created <= REUSE_WINDOW
    )


def reuse_order(user, source):
    """Free re-issue of a recently used number (supplier allows 15 minutes)."""
    if source.user_id != user.id or not can_reuse(source):
        raise OrderError("This number can no longer be reused.")
    try:
        number = pvapins.get_number(source.app_name, source.country_name, reuse_number=source.number)
    except pvapins.SupplierError as exc:
        raise OrderError(exc.message)
    minutes = SiteSetting.get().temp_number_minutes
    return Order.objects.create(
        user=user, kind=Order.TEMP, country_id=source.country_id, country_name=source.country_name,
        app_id=source.app_id, app_name=source.app_name, number=number, price=Decimal("0"), cost=Decimal("0"),
        reuse_of=source, expires_at=timezone.now() + timedelta(minutes=minutes),
    )


@transaction.atomic
def _refund_once(order_id, note):
    order = Order.objects.select_for_update().get(pk=order_id)
    if order.refunded or order.price <= 0:
        return order
    wallet.refund(order.user, order.price, reference=f"order-{order.pk}", note=note)
    order.refunded = True
    order.save(update_fields=["refunded"])
    return order


def refresh(order):
    """Poll the supplier for new SMS and apply expiry. Safe to call repeatedly."""
    if order.kind == Order.RENT:
        return _refresh_rent(order)
    if order.status != Order.ACTIVE:
        return order
    now = timezone.now()
    if order.expires_at and now > order.expires_at:
        order.status = Order.EXPIRED
        order.save(update_fields=["status"])
        _refund_once(order.pk, f"Auto-refund (no code): {order.app_name}")
        order.refresh_from_db()
        return order
    if order.last_checked and now - order.last_checked < POLL_MIN_INTERVAL:
        return order
    order.last_checked = now
    order.save(update_fields=["last_checked"])
    try:
        result = pvapins.get_sms(order.number, order.app_name, order.country_name)
    except pvapins.SupplierError:
        return order
    if result.status == "received":
        order.status, order.otp, order.message = Order.COMPLETED, result.code, result.message
        order.save(update_fields=["status", "otp", "message"])
    return order


def reject(order):
    if order.kind == Order.RENT:
        return _reject_rent(order)
    if order.status != Order.ACTIVE:
        raise OrderError("This order is no longer active.")
    order = refresh(order)
    if order.status != Order.ACTIVE:
        raise OrderError("A code just arrived, so this order cannot be cancelled.")
    try:
        ok = pvapins.reject_number(order.number, order.app_name, order.country_name)
    except pvapins.SupplierError as exc:
        raise OrderError(exc.message)
    if not ok:
        raise OrderError("The number cannot be cancelled yet. Try again shortly (a code may still arrive).")
    order.status = Order.REJECTED
    order.save(update_fields=["status"])
    _refund_once(order.pk, f"Refund (cancelled): {order.app_name}")
    order.refresh_from_db()
    return order


# --- rent ---------------------------------------------------------------

def _sync_rent_expiry(order):
    try:
        for row in pvapins.rent_list():
            if str(row.get("number", "")).lstrip("+") == order.number and row.get("expiry"):
                order.expires_at = datetime.strptime(row["expiry"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt_timezone.utc)
                order.save(update_fields=["expires_at"])
                return
    except (pvapins.SupplierError, ValueError, TypeError):
        pass


def _refresh_rent(order):
    now = timezone.now()
    if order.last_checked and now - order.last_checked < POLL_MIN_INTERVAL:
        return order
    order.last_checked = now
    order.save(update_fields=["last_checked"])
    try:
        msgs = pvapins.rent_messages(order.number, order.app_name, order.country_name)
    except pvapins.SupplierError:
        return order
    if msgs != order.messages:
        order.messages = msgs
        first = next((m.get("message", "") for m in msgs if isinstance(m, dict)), "")
        order.otp = (pvapins.parse_sms(first).code if first else "")
        order.save(update_fields=["messages", "otp"])
    if not order.expires_at:
        _sync_rent_expiry(order)
    if order.expires_at and now > order.expires_at and order.status == Order.ACTIVE:
        order.status = Order.EXPIRED
        order.save(update_fields=["status"])
    return order


def renew_rent(order):
    if order.kind != Order.RENT or order.status in (Order.REJECTED,):
        raise OrderError("This rental cannot be renewed.")
    app = pvapins.app_by_id(order.country_id, order.app_id, rent=True)
    cost = app["cost"] if app else order.cost
    price = sell_price(cost)
    _charge(order.user, price, f"Renew rent: {order.app_name}")
    try:
        pvapins.rent_renew(order.number, order.app_name, order.country_name)
    except pvapins.SupplierError as exc:
        wallet.adjust(order.user, price, "refund", note=f"Refund (renew failed): {order.app_name}")
        raise OrderError(exc.message)
    order.status = Order.ACTIVE
    order.save(update_fields=["status"])
    order.expires_at = None
    order.save(update_fields=["expires_at"])
    _sync_rent_expiry(order)
    return order


def _reject_rent(order):
    if order.status != Order.ACTIVE:
        raise OrderError("This rental is no longer active.")
    order = _refresh_rent(order)
    try:
        pvapins.rent_reject(order.number, order.app_name, order.country_name)
    except pvapins.SupplierError as exc:
        raise OrderError(exc.message)
    order.status = Order.REJECTED
    order.save(update_fields=["status"])
    if not order.messages:  # only refund a rental that never received an SMS
        _refund_once(order.pk, f"Refund (rental released): {order.app_name}")
    order.refresh_from_db()
    return order
