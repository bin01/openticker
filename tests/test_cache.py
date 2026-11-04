"""When Yahoo fails for a moment: a failed fetch is tried once more, then the last good copy is served,
from memory or from the last run's file. Nothing here touches the network."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import server  # noqa: E402


class Flaky:
    def __init__(self, fails, value="fresh"):
        self.fails, self.value, self.calls = fails, value, 0

    def __call__(self):
        self.calls += 1
        if self.calls <= self.fails:
            raise RuntimeError("401 Unauthorized")
        return self.value


class Cache(unittest.TestCase):
    def setUp(self):
        self.p = [mock.patch.object(server, "_detail_cache", {}), mock.patch.object(server, "_disk_cache", {}),
                  mock.patch.object(server, "_stale_keys", set()), mock.patch.object(server.time, "sleep", lambda s: None)]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()

    def test_one_blip_is_retried(self):
        f = Flaky(1)
        self.assertEqual(server.cached(("x", "analysts", "AAPL", ()), 60, f), "fresh")
        self.assertEqual(f.calls, 2)

    def test_last_run_copy_when_yahoo_stays_down(self):
        key = ("x", "analysts", "AAPL", ())
        server._disk_cache[server._disk_key(key)] = (1.0, {"targets": [1]})
        self.assertEqual(server.cached(key, 60, Flaky(9)), {"targets": [1]})
        self.assertIsNotNone(server.stale_age(key))

    def test_memory_copy_beats_failure(self):
        key = ("info", "AAPL")
        server.cached(key, 0, lambda: {"a": 1})
        self.assertEqual(server.cached(key, 0, Flaky(9)), {"a": 1})

    def test_saved_copy_survives_a_restart(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d, mock.patch.object(server, "DETAIL_CACHE", Path(d) / "detail.json"):
            key = ("x", "analysts", "MSFT", ())
            server.cached(key, 60, lambda: {"targets": [2.5]})
            server.save_disk_cache()
            server._detail_cache.clear()
            server.load_disk_cache()
            self.assertEqual(server.cached(key, 60, Flaky(9)), {"targets": [2.5]})

    def test_nothing_to_fall_back_on_raises(self):
        with self.assertRaises(RuntimeError):
            server.cached(("x", "options", "ZZZZ", ()), 60, Flaky(9))


if __name__ == "__main__":
    unittest.main()
