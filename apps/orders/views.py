from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import services
from .models import Order


def _own(request, pk):
    return get_object_or_404(Order, pk=pk, user=request.user)


@login_required
def dashboard(request):
    orders = Order.objects.filter(user=request.user)
    stats = orders.exclude(refunded=True).aggregate(spent=Sum("price"))
    return render(request, "orders/dashboard.html", {
        "active": orders.filter(status=Order.ACTIVE)[:10],
        "recent": orders[:8],
        "total_orders": orders.count(),
        "spent": stats["spent"] or 0,
    })


@login_required
def order_list(request):
    return render(request, "orders/list.html", {"orders": Order.objects.filter(user=request.user)[:200]})


@login_required
def order_detail(request, pk):
    order = services.refresh(_own(request, pk))
    return render(request, "orders/detail.html", {"order": order, "can_reuse": services.can_reuse(order)})


@login_required
def order_status(request, pk):
    order = services.refresh(_own(request, pk))
    remaining = None
    if order.expires_at:
        remaining = max(0, int((order.expires_at - timezone.now()).total_seconds()))
    return JsonResponse({
        "status": order.status,
        "status_label": order.get_status_display(),
        "otp": order.otp,
        "message": order.message,
        "messages": order.messages if order.is_rent else [],
        "refunded": order.refunded,
        "remaining": remaining,
    })


@login_required
@require_POST
def buy(request):
    rent = request.POST.get("rent") == "1"
    try:
        country_id, app_id = int(request.POST["country"]), int(request.POST["app"])
    except (KeyError, ValueError):
        messages.error(request, "Invalid product.")
        return redirect("rent" if rent else "buy")
    try:
        order = services.place_order(request.user, country_id, app_id, rent=rent)
    except services.OrderError as exc:
        if str(exc) == "insufficient":
            messages.error(request, "Not enough balance. Add funds to your wallet first.")
            return redirect("wallet")
        messages.error(request, str(exc))
        return redirect("rent" if rent else "buy")
    return redirect("order_detail", pk=order.pk)


@login_required
@require_POST
def reject(request, pk):
    order = _own(request, pk)
    try:
        services.reject(order)
        messages.success(request, "Order cancelled and refunded to your wallet.")
    except services.OrderError as exc:
        messages.error(request, str(exc))
    return redirect("order_detail", pk=pk)


@login_required
@require_POST
def reuse(request, pk):
    try:
        order = services.reuse_order(request.user, _own(request, pk))
    except services.OrderError as exc:
        messages.error(request, str(exc))
        return redirect("order_detail", pk=pk)
    return redirect("order_detail", pk=order.pk)


@login_required
@require_POST
def renew(request, pk):
    order = _own(request, pk)
    try:
        services.renew_rent(order)
        messages.success(request, "Rental renewed.")
    except services.OrderError as exc:
        if str(exc) == "insufficient":
            messages.error(request, "Not enough balance to renew. Add funds first.")
            return redirect("wallet")
        messages.error(request, str(exc))
    return redirect("order_detail", pk=pk)
