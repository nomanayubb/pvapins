from django.urls import path

from . import views

urlpatterns = [
    path("", views.order_list, name="orders"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("buy/", views.buy, name="place_order"),
    path("<int:pk>/", views.order_detail, name="order_detail"),
    path("<int:pk>/status/", views.order_status, name="order_status"),
    path("<int:pk>/reject/", views.reject, name="order_reject"),
    path("<int:pk>/reuse/", views.reuse, name="order_reuse"),
    path("<int:pk>/renew/", views.renew, name="order_renew"),
]
