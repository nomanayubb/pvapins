from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("buy/", views.catalog, name="buy"),
    path("rent/", views.rent, name="rent"),
    path("countries/", views.countries_page, name="countries"),
    path("pricing/", views.pricing, name="pricing"),
    path("faq/", views.static_page("faq"), name="faq"),
    path("contact/", views.static_page("contact"), name="contact"),
    path("terms/", views.static_page("terms"), name="terms"),
    path("privacy/", views.static_page("privacy"), name="privacy"),
    path("refund/", views.static_page("refund"), name="refund"),
]
