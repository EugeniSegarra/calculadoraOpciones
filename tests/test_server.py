"""Exercise the real local HTTP API, including validation/security boundaries."""
import http.client
import json
import threading
import unittest

from optionslab.server import create_server


class LocalServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server(0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        status, content, hdrs = response.status, response.read(), dict(response.getheaders())
        connection.close()
        return status, content, hdrs

    def test_health_and_example_end_to_end(self):
        status, content, _ = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(content)["status"], "ok")
        _, content, _ = self.request("GET", "/api/demo")
        portfolio = json.loads(content)
        status, content, _ = self.request("POST", "/api/analyze", json.dumps({"portfolio": portfolio}), {"Content-Type": "application/json"})
        self.assertEqual(status, 200)
        self.assertIn("model_pnl", json.loads(content)["summary"])

    def test_host_header_rebinding_rejected(self):
        self.assertEqual(self.request("GET", "/api/demo", headers={"Host": "attacker.example"})[0], 403)

    def test_external_origin_rejected(self):
        self.assertEqual(self.request("POST", "/api/analyze", "{}", {"Content-Type": "application/json", "Origin": "https://attacker.example"})[0], 403)

    def test_content_type_is_required(self):
        self.assertEqual(self.request("POST", "/api/analyze", "{}", {"Content-Type": "text/plain"})[0], 415)

    def test_import_validation_rejects_unknown_contract_terms(self):
        _, content, _ = self.request("GET", "/api/demo")
        portfolio = json.loads(content)
        portfolio["legs"][0]["underlying"] = "DIFFERENT_ASSET"
        status, contents, _ = self.request("POST", "/api/validate", json.dumps({"portfolio": portfolio}), {"Content-Type": "application/json"})
        self.assertEqual(status, 422)
        self.assertIn("underlying", json.loads(contents)["error"])

    def test_invalid_json_and_schema_are_clear_errors(self):
        for body in ("{", "[]", "{}", '{"portfolio": NaN}'):
            with self.subTest(body=body):
                status, contents, _ = self.request("POST", "/api/analyze", body, {"Content-Type": "application/json"})
                self.assertEqual(status, 422)
                self.assertIn("error", json.loads(contents))

    def test_static_paths_and_security_headers(self):
        status, body, headers = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"OptionsLab", body)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(self.request("GET", "/../optionslab/portfolio.py")[0], 404)
        self.assertEqual(self.request("GET", "/.git/config")[0], 404)


if __name__ == "__main__":
    unittest.main()
