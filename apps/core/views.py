from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import render

from . import pvapins
from .pricing import sell_price
from .models import SiteSetting

PAGE_SIZE = 50
DEFAULT_COUNTRY_ID = 58  # USA is first in the supplier's list


def priced_rows(country_id, rent=False, query="", trending_only=False):
    setting = SiteSetting.get()
    rows = []
    q = query.strip().lower()
    for app in pvapins.apps(country_id, rent):
        if trending_only and not app["trending"]:
            continue
        if q and q not in app["name"].lower():
            continue
        rows.append({**app, "price": sell_price(app["cost"], setting)})
    return rows


def home(request):
    ctx = {"countries": [], "trending": []}
    try:
        ctx["countries"] = pvapins.countries()[:12]
        ctx["trending"] = priced_rows(DEFAULT_COUNTRY_ID, trending_only=True)[:12]
    except pvapins.SupplierError:
        pass
    return render(request, "core/home.html", ctx)


def catalog(request, rent=False):
    ctx = {"rent": rent, "rows": None, "countries": [], "country": None}
    try:
        countries = pvapins.countries(rent)
    except pvapins.SupplierError as exc:
        messages.error(request, f"Catalogue is temporarily unavailable: {exc.message}")
        return render(request, "core/catalog.html", ctx)

    ctx["countries"] = countries
    try:
        country_id = int(request.GET.get("country") or (countries[0]["id"] if countries else 0))
    except ValueError:
        country_id = countries[0]["id"] if countries else 0
    country = next((c for c in countries if c["id"] == country_id), countries[0] if countries else None)
    ctx["country"] = country
    if country:
        query = request.GET.get("q", "")
        trending = request.GET.get("trending") == "1"
        try:
            rows = priced_rows(country["id"], rent, query, trending)
        except pvapins.SupplierError as exc:
            messages.error(request, f"Could not load products: {exc.message}")
            rows = []
        page = Paginator(rows, PAGE_SIZE).get_page(request.GET.get("page"))
        ctx.update({"page": page, "q": query, "trending": trending, "total": len(rows)})
    return render(request, "core/catalog.html", ctx)


def rent(request):
    return catalog(request, rent=True)


def countries_page(request):
    q = request.GET.get("q", "").strip().lower()
    try:
        items = [c for c in pvapins.countries() if q in c["name"].lower()]
    except pvapins.SupplierError as exc:
        messages.error(request, exc.message)
        items = []
    return render(request, "core/countries.html", {"items": items, "q": request.GET.get("q", "")})


def pricing(request):
    sections = []
    try:
        for country in pvapins.countries()[:3]:
            sections.append({"country": country, "rows": priced_rows(country["id"], trending_only=True)[:15]})
    except pvapins.SupplierError as exc:
        messages.error(request, exc.message)
    return render(request, "core/pricing.html", {"sections": sections})


def static_page(template):
    def view(request):
        return render(request, f"core/{template}.html")

    return view
