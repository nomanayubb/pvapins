from django.urls import path

from . import views

urlpatterns = [
    path("", views.wallet_page, name="wallet"),
    path("deposit/", views.create_deposit, name="deposit"),
    path("ipn/", views.ipn, name="ipn"),
]
