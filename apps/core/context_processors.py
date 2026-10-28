from django.conf import settings


def site(request):
    balance = None
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        from apps.wallet.models import Wallet

        balance = Wallet.objects.filter(user=user).values_list("balance", flat=True).first()
        balance = balance if balance is not None else 0
    return {
        "SITE_NAME": settings.SITE_NAME,
        "SUPPORT_EMAIL": settings.SUPPORT_EMAIL,
        "SUPPORT_TELEGRAM": settings.SUPPORT_TELEGRAM,
        "nav_balance": balance,
    }
