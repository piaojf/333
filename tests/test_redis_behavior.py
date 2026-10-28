"""Opt-in HTTP tests with a dedicated local Redis process."""
import concurrent.futures
import json
import os
import queue
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@unittest.skipUnless(os.environ.get("REDIS_TEST_SERVER") and os.environ.get("REDIS_TEST_CLI"),
                     "set REDIS_TEST_SERVER and REDIS_TEST_CLI to run real Redis tests")
class RedisBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="redis-behavior-test-")
        cls.addClassCleanup(cls.directory.cleanup)
        cls.redis_port = free_port()
        cls.start_redis()
        cls.addClassCleanup(cls.stop_redis)
        env = dict(os.environ, REDIS_URL=f"redis://127.0.0.1:{cls.redis_port}/0")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            cls.base_url = f"http://127.0.0.1:{listener.getsockname()[1]}"
            cls.api = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app:app", "--fd", str(listener.fileno())],
                env=env, pass_fds=(listener.fileno(),), stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        cls.addClassCleanup(cls.stop_process, cls.api)
        cls.wait_ready(cls.base_url + "/docs", cls.api)

    @staticmethod
    def stop_process(process):
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)

    @classmethod
    def start_redis(cls):
        cls.redis = subprocess.Popen(
            [os.environ["REDIS_TEST_SERVER"], "--bind", "127.0.0.1", "--port", str(cls.redis_port),
             "--dir", cls.directory.name, "--appendonly", "yes", "--appendfsync", "always"],
            env=dict(os.environ, LC_ALL="C"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if cls.redis.poll() is not None:
                raise RuntimeError("Redis exited before becoming ready")
            try:
                info = subprocess.run(
                    [os.environ["REDIS_TEST_CLI"], "-h", "127.0.0.1", "-p", str(cls.redis_port),
                     "INFO", "server"], capture_output=True, text=True, timeout=1, check=True,
                ).stdout
                if re.search(rf"(?m)^process_id:{cls.redis.pid}\s*$", info):
                    return
            except (OSError, subprocess.SubprocessError):
                pass
            if cls.redis.poll() is None:
                time.sleep(0.05)
        cls.stop_redis()
        raise TimeoutError("Redis did not become ready")

    @classmethod
    def stop_redis(cls):
        cls.stop_process(cls.redis)

    @staticmethod
    def wait_ready(url, process):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("API exited before becoming ready")
            try:
                with urllib.request.urlopen(url, timeout=0.5):
                    return
            except (OSError, urllib.error.URLError):
                time.sleep(0.05)
        raise TimeoutError("API did not become ready")

    def setUp(self):
        self.key = uuid.uuid4().int % (2**62) + 1

    def request(self, method, value=None):
        body = None if value is None else json.dumps({"value": value}).encode()
        req = urllib.request.Request(
            f"{self.base_url}/values/{self.key}", data=body, method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def test_unavailable_redis_rejects_reads_and_writes(self):
        self.assertEqual(self.request("PUT", "before")[0], 200)
        self.stop_redis()
        try:
            with socket.socket() as reservation:
                reservation.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                reservation.bind(("127.0.0.1", self.redis_port))
                reservation.listen()
                reservation.settimeout(0.1)
                done = threading.Event()

                def reject_connections():
                    while not done.is_set():
                        try:
                            connection, _ = reservation.accept()
                        except socket.timeout:
                            continue
                        connection.close()

                rejector = threading.Thread(target=reject_connections)
                rejector.start()
                try:
                    self.assertEqual(self.request("GET")[0], 503)
                    self.assertEqual(self.request("PUT", "during outage")[0], 503)
                finally:
                    done.set()
                    rejector.join()
        finally:
            self.start_redis()
        self.assertEqual(self.request("GET"), (200, {"key": self.key, "value": "before"}))

    def test_concurrent_writes_follow_redis_processing_order(self):
        monitor = subprocess.Popen(
            [os.environ["REDIS_TEST_CLI"], "-h", "127.0.0.1", "-p", str(self.redis_port), "MONITOR"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1,
        )
        lines = queue.Queue()

        def collect():
            for line in monitor.stdout:
                lines.put(line.strip())
            lines.put(None)

        reader = threading.Thread(target=collect, daemon=True)
        reader.start()
        try:
            self.assertEqual(lines.get(timeout=10), "OK", "Redis MONITOR did not start")
            values = [f"write-{i}" for i in range(16)]
            barrier = threading.Barrier(len(values))

            def write(value):
                barrier.wait(timeout=10)
                return self.request("PUT", value)

            with concurrent.futures.ThreadPoolExecutor(max_workers=len(values)) as executor:
                responses = list(executor.map(write, values))
            for value, response in zip(values, responses):
                self.assertEqual(response, (200, {"key": self.key, "value": value}))

            pattern = re.compile(r'"SET" "' + str(self.key) + r'" "(write-\d+)"', re.IGNORECASE)
            processed = []
            deadline = time.monotonic() + 10
            while len(processed) < len(values):
                remaining = deadline - time.monotonic()
                self.assertGreater(remaining, 0, "Redis MONITOR missed writes")
                line = lines.get(timeout=remaining)
                self.assertIsNotNone(line, "Redis MONITOR exited early")
                match = pattern.search(line)
                if match:
                    processed.append(match.group(1))
            self.assertCountEqual(processed, values)
            self.assertEqual(self.request("GET"), (200, {"key": self.key, "value": processed[-1]}))
        finally:
            self.stop_process(monitor)
            reader.join(timeout=10)
            monitor.stdout.close()
            monitor.stderr.close()


if __name__ == "__main__":
    unittest.main()
