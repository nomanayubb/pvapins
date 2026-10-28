from django.conf import settings
from django.db import models


class Order(models.Model):
    TEMP, RENT = "temp", "rent"
    ACTIVE, COMPLETED, REJECTED, EXPIRED = "active", "completed", "rejected", "expired"
    STATUSES = [(ACTIVE, "Waiting for code"), (COMPLETED, "Completed"), (REJECTED, "Rejected"), (EXPIRED, "Expired")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="orders")
    kind = models.CharField(max_length=4, default=TEMP)
    country_id = models.PositiveIntegerField()
    country_name = models.CharField(max_length=80)
    app_id = models.PositiveIntegerField()
    app_name = models.CharField(max_length=160)
    number = models.CharField(max_length=24)
    price = models.DecimalField(max_digits=10, decimal_places=2, help_text="Charged to the customer (USD).")
    cost = models.DecimalField(max_digits=10, decimal_places=2, help_text="Supplier price (USD).")
    status = models.CharField(max_length=10, choices=STATUSES, default=ACTIVE)
    otp = models.CharField(max_length=64, blank=True)
    message = models.TextField(blank=True)
    messages = models.JSONField(default=list, blank=True, help_text="Rent orders: every SMS received.")
    reuse_of = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="reuses")
    refunded = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    last_checked = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created", "-id"]
        indexes = [models.Index(fields=["user", "-created"])]

    def __str__(self):
        return f"#{self.pk} {self.app_name} {self.number}"

    @property
    def is_rent(self):
        return self.kind == self.RENT
