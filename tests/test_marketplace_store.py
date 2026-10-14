import os
import tempfile
import unittest

from app import app


class MarketplaceApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["SMITHX_DB_PATH"] = os.path.join(self.tmp.name, "test.sqlite3")
        os.environ["SMITHX_AUTH_SECRET"] = "test-secret-that-is-at-least-32-characters-long"
        self.client = app.test_client()
        registration = self.client.post("/api/marketplace/seller/register", json={"email": "seller@example.test", "password": "a-strong-test-password"})
        self.assertEqual(registration.status_code, 201)
        self.seller = registration.get_json()["seller"]
        self.headers = {"Authorization": "Bearer " + registration.get_json()["token"]}

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("SMITHX_DB_PATH", None)
        os.environ.pop("SMITHX_AUTH_SECRET", None)

    def test_health(self):
        response = self.client.get("/api/marketplace/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["storage"], "sqlite")

    def test_product_persists_and_order_is_pending_not_paid(self):
        product_response = self.client.post("/api/marketplace/products", json={
            "title": "Sample item", "price": 12.50,
            "currency": "KES", "inventory": 3,
        }, headers=self.headers)
        self.assertEqual(product_response.status_code, 201)
        product = product_response.get_json()["product"]
        self.assertEqual(product["price"], 12.5)

        listed = self.client.get("/api/marketplace/products?seller_id=" + self.seller["id"])
        self.assertEqual(len(listed.get_json()["products"]), 1)

        order_response = self.client.post("/api/marketplace/orders", json={
            "customer_id": "customer-test",
            "items": [{"product_id": product["id"], "quantity": 2}],
        })
        self.assertEqual(order_response.status_code, 201)
        order = order_response.get_json()["order"]
        self.assertEqual(order["subtotal"], 25.0)
        self.assertEqual(order["status"], "pending")
        self.assertEqual(order["payment_status"], "not_processed")

        fetched = self.client.get("/api/marketplace/orders/" + order["id"])
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.get_json()["order"]["subtotal"], 25.0)
        remaining = self.client.get("/api/marketplace/products?seller_id=" + self.seller["id"])
        self.assertEqual(remaining.get_json()["products"][0]["inventory"], 1)

    def test_invalid_product_and_insufficient_inventory(self):
        unauthenticated = self.client.post("/api/marketplace/products", json={"title": "No token"})
        self.assertEqual(unauthenticated.status_code, 401)
        bad = self.client.post("/api/marketplace/products", json={"title": ""}, headers=self.headers)
        self.assertEqual(bad.status_code, 400)
        product = self.client.post("/api/marketplace/products", json={
            "title": "Limited", "price": 1, "inventory": 1,
        }, headers=self.headers).get_json()["product"]
        order = self.client.post("/api/marketplace/orders", json={
            "customer_id": "c1", "items": [{"product_id": product["id"], "quantity": 2}],
        })
        self.assertEqual(order.status_code, 409)

    def test_seller_analytics_is_authenticated_and_scoped(self):
        denied = self.client.get("/api/marketplace/seller/analytics")
        self.assertEqual(denied.status_code, 401)
        product_response = self.client.post("/api/marketplace/products", json={
            "title": "Analytics item", "price": 8.25, "currency": "EUR", "inventory": 4,
            "seller_id": "attacker-controlled-id",
        }, headers=self.headers)
        self.assertEqual(product_response.status_code, 201)
        product = product_response.get_json()["product"]
        self.assertEqual(product["seller_id"], self.seller["id"])
        view = self.client.post("/api/marketplace/seller/events/product-view", json={
            "product_id": product["id"], "visitor_key": "random-visitor-key-123456",
        })
        self.assertEqual(view.status_code, 202)
        order = self.client.post("/api/marketplace/orders", json={
            "customer_id": "analytics-customer",
            "items": [{"product_id": product["id"], "quantity": 2}],
        })
        self.assertEqual(order.status_code, 201)
        analytics = self.client.get("/api/marketplace/seller/analytics?since=all", headers=self.headers)
        self.assertEqual(analytics.status_code, 200)
        self.assertEqual(analytics.get_json()["products_listed"], 1)
        self.assertEqual(analytics.get_json()["product_views"], 1)
        self.assertEqual(analytics.get_json()["unique_visitors"], 1)
        self.assertIsNone(analytics.get_json()["profit_estimate"])
        payload = analytics.get_json()
        self.assertEqual(payload["default_currency"], "EUR")
        self.assertEqual(payload["currency_totals"]["EUR"]["gross_order_value"], 16.5)
        self.assertNotIn("gross_order_value", payload)

    def test_seller_login_and_duplicate_registration(self):
        duplicate = self.client.post("/api/marketplace/seller/register", json={
            "email": "SELLER@example.test", "password": "another-strong-password",
        })
        self.assertEqual(duplicate.status_code, 409)
        login = self.client.post("/api/marketplace/seller/login", json={
            "email": "seller@example.test", "password": "a-strong-test-password",
        })
        self.assertEqual(login.status_code, 200)
        wrong = self.client.post("/api/marketplace/seller/login", json={
            "email": "seller@example.test", "password": "wrong-password-123",
        })
        self.assertEqual(wrong.status_code, 401)


if __name__ == "__main__":
    unittest.main()
