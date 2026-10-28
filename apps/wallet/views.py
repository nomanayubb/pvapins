import json
import logging
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.core.models import SiteSetting

from . import nowpayments, services
from .models import Deposit, Transaction

log = logging.getLogger(__name__)

MAX_DEPOSIT = Decimal("5000")


@login_required
def wallet_page(request):
    setting = SiteSetting.get()
    return render(request, "wallet/wallet.html", {
        "deposits": Deposit.objects.filter(user=request.user)[:10],
        "transactions": Transaction.objects.filter(user=request.user)[:30],
        "min_deposit": setting.min_deposit_usd,
        "presets": [5, 10, 25, 50, 100],
        "paid": request.GET.get("paid") == "1",
    })


@login_required
@require_POST
def create_deposit(request):
    setting = SiteSetting.get()
    try:
        amount = Decimal(request.POST.get("amount", "")).quantize(Decimal("0.01"))
    except InvalidOperation:
        messages.error(request, "Enter a valid amount.")
        return redirect("wallet")
    if amount < setting.min_deposit_usd or amount > MAX_DEPOSIT:
        messages.error(request, f"Amount must be between ${setting.min_deposit_usd} and ${MAX_DEPOSIT}.")
        return redirect("wallet")

    deposit = Deposit.objects.create(user=request.user, usd_amount=amount)
    try:
        invoice = nowpayments.create_invoice(deposit)
    except nowpayments.NowPaymentsError as exc:
        deposit.status = "failed"
        deposit.note = str(exc)[:200]
        deposit.save(update_fields=["status", "note", "updated"])
        messages.error(request, str(exc))
        return redirect("wallet")
    deposit.invoice_id = str(invoice.get("id", ""))
    deposit.invoice_url = invoice["invoice_url"]
    deposit.save(update_fields=["invoice_id", "invoice_url", "updated"])
    return redirect(deposit.invoice_url)


@csrf_exempt
@require_POST
def ipn(request):
    try:
        payload = json.loads(request.body)
    except ValueError:
        return HttpResponseBadRequest("bad json")
    if not isinstance(payload, dict) or not nowpayments.verify_ipn(payload, request.headers.get("x-nowpayments-sig", "")):
        log.warning("NOWPayments IPN rejected: bad signature")
        return HttpResponse(status=401)

    deposit = Deposit.objects.filter(order_id=str(payload.get("order_id", ""))).first()
    if deposit is None:
        return HttpResponse("unknown order", status=200)  # ack so it is not retried forever

    status = str(payload.get("payment_status", ""))
    deposit.status = status or deposit.status
    deposit.payment_id = str(payload.get("payment_id", deposit.payment_id))
    deposit.pay_currency = str(payload.get("pay_currency", deposit.pay_currency))
    deposit.actually_paid = str(payload.get("actually_paid", deposit.actually_paid))
    deposit.save()

    if status == Deposit.FINISHED:
        if nowpayments.same_amount(payload.get("price_amount"), deposit.usd_amount):
            services.credit_deposit(deposit.pk)
        else:
            deposit.note = "price_amount mismatch - not credited, review manually"
            deposit.save(update_fields=["note", "updated"])
            log.error("Deposit %s price mismatch: ipn=%s ours=%s", deposit.order_id, payload.get("price_amount"), deposit.usd_amount)
    return HttpResponse("ok")
