"""HTTP contract tests with the Redis boundary replaced by an in-memory stub."""
import unittest

from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError

from app import app


class Store:
    def __init__(self):
        self.values = {}
        self.available = True

    async def set(self, key, value):
        if not self.available:
            raise ConnectionError("unavailable")
        self.values[key] = value

    async def get(self, key):
        if not self.available:
            raise ConnectionError("unavailable")
        return self.values.get(key)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        app.state.redis = self.store
        self.client = TestClient(app)

    def test_values_round_trip_and_overwrite(self):
        self.assertEqual(self.client.get('/values/1').status_code, 404)
        for value in ('', '中文 🐈'):
            response = self.client.put('/values/1', json={'value': value})
            self.assertEqual(response.json(), {'key': 1, 'value': value})
            self.assertEqual(self.client.get('/values/1').json(), {'key': 1, 'value': value})
        self.client.put('/values/2', json={'value': 'other'})
        self.assertEqual(self.client.get('/values/1').json()['value'], '中文 🐈')

    def test_rejects_invalid_keys_and_values(self):
        for key in ('0', '01', '-1', '1.5', '9223372036854775808'):
            with self.subTest(key=key):
                self.assertEqual(self.client.get('/values/' + key).status_code, 422)
        invalid_values: tuple[object, ...] = (None, 1, False, [], {})
        for value in invalid_values:
            with self.subTest(value=value):
                self.assertEqual(self.client.put('/values/1', json={'value': value}).status_code, 422)
        self.assertEqual(self.client.put('/values/9223372036854775807', json={'value': 'x'}).status_code, 200)

    def test_size_limit_and_unavailable_store(self):
        self.assertEqual(self.client.put('/values/1', json={'value': 'é' * 524288}).status_code, 200)
        self.assertEqual(self.client.put('/values/1', json={'value': 'é' * 524289}).status_code, 413)
        self.store.available = False
        self.assertEqual(self.client.get('/values/1').status_code, 503)
        self.assertEqual(self.client.put('/values/1', json={'value': 'x'}).status_code, 503)


if __name__ == '__main__':
    unittest.main()
