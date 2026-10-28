from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "SimCode786 admin"
admin.site.site_title = "SimCode786"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("wallet/", include("apps.wallet.urls")),
    path("orders/", include("apps.orders.urls")),
    path("", include("apps.core.urls")),
]
