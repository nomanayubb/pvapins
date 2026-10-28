import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models


def new_order_id():
    return uuid.uuid4().hex


class Wallet(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wallet")
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))

    def __str__(self):
        return f"{self.user} ${self.balance}"


class Transaction(models.Model):
    TOPUP, PURCHASE, REFUND, ADJUST = "topup", "purchase", "refund", "adjust"
    KINDS = [(TOPUP, "Top-up"), (PURCHASE, "Purchase"), (REFUND, "Refund"), (ADJUST, "Adjustment")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="transactions")
    kind = models.CharField(max_length=10, choices=KINDS)
    amount = models.DecimalField(max_digits=12, decimal_places=2, help_text="Signed: negative = money out.")
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    reference = models.CharField(max_length=64, blank=True)
    note = models.CharField(max_length=200, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created", "-id"]
        constraints = [
            # One ledger line per (kind, reference): makes top-ups and refunds idempotent.
            models.UniqueConstraint(
                fields=["kind", "reference"],
                condition=models.Q(kind__in=["topup", "refund"]) & ~models.Q(reference=""),
                name="uniq_credit_per_reference",
            )
        ]


class Deposit(models.Model):
    FINISHED = "finished"
    OPEN_STATES = {"waiting", "confirming", "confirmed", "sending", "partially_paid"}

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="deposits")
    order_id = models.CharField(max_length=40, unique=True, default=new_order_id)
    usd_amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, default="waiting")
    invoice_id = models.CharField(max_length=40, blank=True)
    invoice_url = models.URLField(max_length=300, blank=True)
    payment_id = models.CharField(max_length=40, blank=True)
    pay_currency = models.CharField(max_length=20, blank=True)
    actually_paid = models.CharField(max_length=40, blank=True)
    credited = models.BooleanField(default=False)
    note = models.CharField(max_length=200, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return f"{self.order_id} ${self.usd_amount} {self.status}"
