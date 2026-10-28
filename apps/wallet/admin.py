from django.contrib import admin

from .models import Deposit, Transaction, Wallet


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("user", "balance")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("user", "balance")  # change balances via the ledger, not by editing here


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("created", "user", "kind", "amount", "balance_after", "reference", "note")
    list_filter = ("kind",)
    search_fields = ("user__username", "reference")

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Deposit)
class DepositAdmin(admin.ModelAdmin):
    list_display = ("created", "user", "usd_amount", "status", "pay_currency", "actually_paid", "credited")
    list_filter = ("status", "credited")
    search_fields = ("order_id", "user__username", "payment_id")
