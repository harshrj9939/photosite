import base64
import unittest

from app import app


class AdminPanelTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.auth = base64.b64encode(b"admin:change-this-before-launch").decode("ascii")

    def test_admin_dashboard_renders_summary_and_customers(self):
        response = self.client.get(
            "/admin",
            headers={"Authorization": f"Basic {self.auth}"},
        )

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Photosite orders", html)
        self.assertIn("Order value", html)
        self.assertIn("Action needed", html)
        self.assertIn("Customers", html)


if __name__ == "__main__":
    unittest.main()
