"""Black-box HTTP tests; start the Compose services before running."""
import json
import os
import unittest
import urllib.error
import urllib.request
import uuid

BASE_URL = os.environ.get("API_URL", "http://127.0.0.1:8000")


_NO_BODY = object()


def request(method, key, value=_NO_BODY):
    body = None if value is _NO_BODY else json.dumps({"value": value}, ensure_ascii=False).encode()
    req = urllib.request.Request(f"{BASE_URL}/values/{key}", data=body, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


class ValueApiTests(unittest.TestCase):
    def setUp(self):
        self.key = uuid.uuid4().int % (2**62) + 1

    def test_write_and_read(self):
        expected = {"key": self.key, "value": "hello"}
        self.assertEqual(request("PUT", self.key, "hello"), (200, expected))
        self.assertEqual(request("GET", self.key), (200, expected))

    def test_keys_are_independent_and_overwrite(self):
        other = self.key + 1
        request("PUT", self.key, "first")
        request("PUT", other, "other")
        request("PUT", self.key, "updated")
        self.assertEqual(request("GET", self.key)[1]["value"], "updated")
        self.assertEqual(request("GET", other)[1]["value"], "other")

    def test_key_and_value_validation(self):
        for key in ("0", "01", "-1", "1.5", "9223372036854775808"):
            with self.subTest(key=key):
                self.assertEqual(request("GET", key)[0], 422)
        self.assertIn(request("GET", "9223372036854775807")[0], (200, 404))
        for value in (None, 42, False, ["text"], {"text": "x"}):
            with self.subTest(value=value):
                self.assertEqual(request("PUT", self.key, value)[0], 422)

    def test_utf8_size_limit(self):
        self.assertEqual(request("PUT", self.key, "é" * 524288)[0], 200)
        self.assertEqual(request("PUT", self.key, "é" * 524289)[0], 413)
        self.assertEqual(request("GET", self.key)[1]["value"], "é" * 524288)

    def test_empty_unicode_and_missing(self):
        self.assertEqual(request("GET", self.key)[0], 404)
        self.assertEqual(request("PUT", self.key, "")[0], 200)
        self.assertEqual(request("GET", self.key)[1]["value"], "")
        self.assertEqual(request("PUT", self.key, "中文 🐈")[0], 200)
        self.assertEqual(request("GET", self.key)[1]["value"], "中文 🐈")


if __name__ == "__main__":
    unittest.main()
