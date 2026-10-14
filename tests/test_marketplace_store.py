import os
import tempfile
import unittest

from app import app


class MarketplaceApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["SMITHX_DB_PATH"] = os.path.join(self.tmp.name, "test.sqlite3")
        self.client = app.test_client()

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("SMITHX_DB_PATH", None)

    def test_health(self):
        response = self.client.get("/api/marketplace/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["storage"], "sqlite")

    def test_product_persists_and_order_is_pending_not_paid(self):
        product_response = self.client.post("/api/marketplace/products", json={
            "seller_id": "seller-test", "title": "Sample item", "price": 12.50,
            "currency": "KES", "inventory": 3,
        })
        self.assertEqual(product_response.status_code, 201)
        product = product_response.get_json()["product"]
        self.assertEqual(product["price"], 12.5)

        listed = self.client.get("/api/marketplace/products?seller_id=seller-test")
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
        remaining = self.client.get("/api/marketplace/products?seller_id=seller-test")
        self.assertEqual(remaining.get_json()["products"][0]["inventory"], 1)

    def test_invalid_product_and_insufficient_inventory(self):
        bad = self.client.post("/api/marketplace/products", json={"title": "Missing seller"})
        self.assertEqual(bad.status_code, 400)
        product = self.client.post("/api/marketplace/products", json={
            "seller_id": "s1", "title": "Limited", "price": 1, "inventory": 1,
        }).get_json()["product"]
        order = self.client.post("/api/marketplace/orders", json={
            "customer_id": "c1", "items": [{"product_id": product["id"], "quantity": 2}],
        })
        self.assertEqual(order.status_code, 409)


if __name__ == "__main__":
    unittest.main()
