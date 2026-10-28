"""Opt-in recovery test against an isolated Compose project and real Redis."""
import http.client
import json
import os
import subprocess
import time
import unittest
import urllib.error
import urllib.request
import uuid


@unittest.skipUnless(os.environ.get("PERSISTENCE_TEST_PROJECT"), "requires an isolated Compose project")
class PersistenceTests(unittest.TestCase):
    def test_value_survives_restart_and_recreation(self):
        project = os.environ["PERSISTENCE_TEST_PROJECT"]
        if not project.startswith("persistence-test-"):
            self.fail("PERSISTENCE_TEST_PROJECT must start with persistence-test-")
        address = subprocess.check_output(
            ["docker", "compose", "-p", project, "port", "api", "8000"], text=True
        ).strip()
        base_url = f"http://{address}"
        key = uuid.uuid4().int % (2**62) + 1
        expected = {"key": key, "value": "持久化测试"}
        url = f"{base_url}/values/{key}"
        request = urllib.request.Request(
            url, data=json.dumps({"value": expected["value"]}).encode(),
            headers={"Content-Type": "application/json"}, method="PUT",
        )
        self.assertEqual(self.read_when_ready(request), expected)

        for action in (("restart", "redis"),
                       ("up", "-d", "--no-deps", "--no-build", "--force-recreate", "redis")):
            with self.subTest(action=action):
                subprocess.run(["docker", "compose", "-p", project, *action], check=True)
                self.assertEqual(self.read_when_ready(url), expected)

    def read_when_ready(self, request):
        deadline = time.monotonic() + 30
        while True:
            try:
                with urllib.request.urlopen(request, timeout=2) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                if error.code != 503 or time.monotonic() >= deadline:
                    raise
            except (urllib.error.URLError, TimeoutError, ConnectionError,
                    http.client.RemoteDisconnected):
                if time.monotonic() >= deadline:
                    raise
            time.sleep(0.5)


if __name__ == "__main__":
    unittest.main()
