from decimal import Decimal

from django.core.cache import cache
from django.db import models


class SiteSetting(models.Model):
    """Single-row store settings, editable from the admin."""

    markup_percent = models.DecimalField(
        max_digits=7, decimal_places=2, default=Decimal("100"),
        help_text="Percent added on top of the supplier price. 100 = double (0.12 -> 0.24).",
    )
    min_margin_usd = models.DecimalField(
        max_digits=7, decimal_places=2, default=Decimal("0.05"),
        help_text="Minimum profit per sale in USD, applied when the percent markup would give less.",
    )
    usd_to_pkr = models.DecimalField(
        max_digits=9, decimal_places=2, default=Decimal("280"),
        help_text="Fallback rate, or the rate used when live rate is switched off.",
    )
    auto_pkr_rate = models.BooleanField(default=True, help_text="Fetch the live USD->PKR rate (cached 6h).")
    min_deposit_usd = models.DecimalField(max_digits=7, decimal_places=2, default=Decimal("2"))
    temp_number_minutes = models.PositiveIntegerField(
        default=20, help_text="Minutes to wait for a code before a temporary order auto-refunds.",
    )

    class Meta:
        verbose_name = "store settings"
        verbose_name_plural = "store settings"

    def __str__(self):
        return "Store settings"

    CACHE_KEY = "site_setting"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete(self.CACHE_KEY)

    @classmethod
    def get(cls):
        obj = cache.get(cls.CACHE_KEY)
        if obj is None:
            obj, _ = cls.objects.get_or_create(pk=1)
            cache.set(cls.CACHE_KEY, obj, 30)
        return obj
