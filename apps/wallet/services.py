from decimal import Decimal

from django.db import IntegrityError, transaction

from .models import Deposit, Transaction, Wallet


class InsufficientFunds(Exception):
    pass


@transaction.atomic
def adjust(user, amount, kind, reference="", note=""):
    """Apply a signed amount to the user's wallet and write the ledger line.

    Returns the Transaction, or None when a credit with the same (kind, reference)
    was already applied (so retries and duplicate webhooks never double-credit).
    """
    amount = Decimal(amount)
    wallet, _ = Wallet.objects.get_or_create(user=user)
    wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
    if wallet.balance + amount < 0:
        raise InsufficientFunds()
    try:
        with transaction.atomic():
            wallet.balance += amount
            tx = Transaction.objects.create(
                user=user, kind=kind, amount=amount, balance_after=wallet.balance,
                reference=reference, note=note[:200],
            )
    except IntegrityError:
        return None
    wallet.save(update_fields=["balance"])
    return tx


def debit(user, amount, reference="", note=""):
    return adjust(user, -Decimal(amount), Transaction.PURCHASE, reference, note)


def refund(user, amount, reference, note=""):
    return adjust(user, Decimal(amount), Transaction.REFUND, reference, note)


@transaction.atomic
def credit_deposit(deposit_id):
    """Credit a finished deposit exactly once, using OUR stored USD amount."""
    deposit = Deposit.objects.select_for_update().get(pk=deposit_id)
    if deposit.credited:
        return False
    adjust(deposit.user, deposit.usd_amount, Transaction.TOPUP, deposit.order_id,
           f"Crypto top-up ({deposit.pay_currency.upper() or 'NOWPayments'})")
    deposit.credited = True
    deposit.save(update_fields=["credited", "updated"])
    return True
