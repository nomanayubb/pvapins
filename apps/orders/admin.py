from django.contrib import admin

from .models import Order


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "created", "user", "kind", "country_name", "app_name", "number", "price", "cost", "status", "refunded")
    list_filter = ("kind", "status", "refunded")
    search_fields = ("user__username", "number", "app_name")
    readonly_fields = [f.name for f in Order._meta.fields]

    def has_add_permission(self, request):
        return False
