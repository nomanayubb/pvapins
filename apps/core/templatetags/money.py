from decimal import Decimal

from django import template

from apps.core.pricing import to_pkr

register = template.Library()


def fmt_pkr(value):
    value = Decimal(str(value))
    return f"Rs {value:,.0f}" if value >= 100 else f"Rs {value:,.2f}"


@register.filter
def usd(value):
    return f"${Decimal(str(value)):,.2f}"


@register.filter
def pkr(value):
    return fmt_pkr(to_pkr(value))


@register.filter
def money(value):
    """$0.24 with the PKR amount next to it."""
    return f"${Decimal(str(value)):,.2f} ({fmt_pkr(to_pkr(value))})"
