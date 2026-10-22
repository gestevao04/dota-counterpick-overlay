import os
import unittest
from unittest import mock

import updater
from tests.helpers import build_world, cs, dr, reset_home


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        reset_home()

    def _stub_downloads(self, **overrides):
        calls = []
        fakes = {"portraits": lambda p: calls.append("portraits"),
                 "matchups": lambda p: calls.append("matchups"),
                 "meta": lambda p: calls.append("meta")}
        fakes.update(overrides)
        for obj, name, key in ((dr, "fetch", "portraits"), (cs, "fetch", "matchups"), (cs, "fetch_meta", "meta")):
            patcher = mock.patch.object(obj, name, fakes[key])
            patcher.start()
            self.addCleanup(patcher.stop)
        return calls

    def test_runs_in_a_fixed_order(self):
        calls = self._stub_downloads()
        results = updater.run(["meta", "portraits", "matchups"])
        self.assertEqual(calls, ["portraits", "matchups", "meta"])
        self.assertTrue(all(ok for _, ok, _ in results))

    def test_token_error_skips_the_other_stratz_task_but_not_portraits(self):
        def rejected(progress):
            raise cs.StratzError("Stratz rejected the token (HTTP 401). Check it at stratz.com/api.")

        calls = self._stub_downloads(matchups=rejected)
        results = updater.run(["portraits", "matchups", "meta"])
        self.assertEqual([ok for _, ok, _ in results], [True, False, False])
        self.assertEqual(calls, ["portraits"])
        self.assertIn("token", results[2][2])

    def test_never_raises(self):
        def offline(progress):
            raise cs.requests.ConnectionError("offline")

        self._stub_downloads(matchups=offline)
        result = updater.run(["matchups"])[0]
        self.assertFalse(result[1])
        self.assertIn("Network", result[2])

        def broken(progress):
            raise ZeroDivisionError()

        self._stub_downloads(matchups=broken)
        result = updater.run(["matchups"])[0]
        self.assertFalse(result[1])
        self.assertIn("Unexpected", result[2])


class StatusTests(unittest.TestCase):
    def setUp(self):
        reset_home()

    def test_nothing_downloaded(self):
        self.assertFalse(updater.is_ready())
        self.assertEqual({s for s, _ in updater.status().values()}, {"missing"})

    def test_ready_and_stale_bracket(self):
        build_world()
        self.assertTrue(updater.is_ready())
        self.assertEqual(updater.status()["matchups"][0], "ok")
        cs.save_config(bracket="CRUSADER_ARCHON")
        state, text = updater.status()["matchups"]
        self.assertEqual(state, "stale")
        self.assertIn("bracket changed", text)

    def test_old_position_data_format_is_called_out(self):
        build_world()
        (cs.CACHE / "meta.json").write_text('{"1": {"1": [10, 5]}}')
        self.assertIn("old format", updater.status()["meta"][1])


if __name__ == "__main__":
    unittest.main()
