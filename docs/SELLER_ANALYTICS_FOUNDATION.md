# SMITHX seller authentication and analytics foundation

This change adds the first server-side seller-account and analytics API foundation. It is not a deployment and does not yet connect the static GitHub Pages dashboard to these endpoints.

## Required configuration

Before enabling seller registration or authenticated seller endpoints, configure SMITHX_AUTH_SECRET as a randomly generated secret of at least 32 characters. Keep it private and set it through the hosting provider's secret/environment settings, never in the frontend repository. Rotating it invalidates existing seller tokens.

The existing SMITHX_DB_PATH setting selects the SQLite database file. SQLite is suitable for development/small tests, not the agreed production PostgreSQL architecture. Confirm persistent disk support before deploying SQLite anywhere.

## Endpoints

- POST /api/marketplace/seller/register: JSON { "email": "...", "password": "at-least-12-characters" }; creates a seller and returns a seven-day bearer token.
- POST /api/marketplace/seller/login: returns a new bearer token after credential verification.
- POST /api/marketplace/products: now requires Authorization: Bearer <token>; seller ownership is derived from the signed token, not the request body.
- GET /api/marketplace/seller/analytics?since=today|7d|30d|all: authenticated seller-scoped counts and sales/order summaries.
- POST /api/marketplace/seller/events/product-view: JSON { "product_id": "...", "visitor_key": "random-opaque-id-at-least-16-chars" }; records a product detail view. Use a random, short-lived identifier and do not send names, emails, IP addresses, or other direct identifiers.

## Financial and analytics limitations

- Orders are still test/pending orders, not verified paid sales. The analytics endpoint excludes cancelled/refunded status labels but cannot verify payment.
- profit_estimate is deliberately null until product costs and payment/shipping/tax/fee data are captured. Do not present gross order value as profit.
- Unique visitors are approximated by distinct client-provided opaque visitor keys; clients can reset or spoof them. This is not fraud-resistant traffic measurement.
- The API currently stores data in SQLite and still has no customer authentication, payment provider, PostgreSQL migrations, rate limiting, email verification, password reset, account recovery, or production session revocation.
- CORS is still configured globally in app.py; before production, restrict allowed origins to the intended SMITHX domains.
- Seller registration should receive rate limiting and abuse monitoring before public exposure.

## Validation

The pull request includes tests for registration/login, duplicate accounts, unauthenticated product writes, seller ownership derived from token, analytics access control, and product-view aggregation. GitHub Actions must report a passing run before merge.
