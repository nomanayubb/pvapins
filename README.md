# SimCode786

Django site for virtual phone numbers / SMS verification (buy + rent), with a crypto wallet.

- Catalogue and orders go through a server-side supplier client (`apps/core/pvapins.py`); the supplier's name, URL and key never reach the browser.
- Selling price = supplier cost + markup (default 100%, min margin $0.05), editable in admin -> Store settings. Prices show in USD with PKR next to them.
- Wallet top-ups: NOWPayments hosted invoice. Credit happens only from a signature-verified IPN, once per payment.

## Run locally

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env      # then fill in the keys
.venv\Scripts\python manage.py migrate
.venv\Scripts\python manage.py createsuperuser
.venv\Scripts\python manage.py runserver
```

Tests: `.venv\Scripts\python manage.py test`

## NOWPayments setup

1. Store settings -> API keys: create a key -> `NOWPAYMENTS_API_KEY`.
2. Store settings -> Instant payment notifications: generate an **IPN secret** -> `NOWPAYMENTS_IPN_SECRET`.
3. Payment settings: enable the coins you accept and set a payout wallet for each (or enable auto-conversion).
4. The IPN callback URL is sent with every invoice as `SITE_URL/wallet/ipn/`, so `SITE_URL` must be a public https address (use a tunnel such as ngrok while developing).
5. `NOWPAYMENTS_SANDBOX=1` only works with sandbox keys from the separate sandbox account.

## Production notes

- `DJANGO_DEBUG=0`, a long random `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`.
- Use PostgreSQL instead of SQLite and run behind HTTPS (gunicorn + a reverse proxy); `python manage.py collectstatic`.
- The supplier allows about 5 new numbers per minute per key: expect "try again" errors under heavy load.
