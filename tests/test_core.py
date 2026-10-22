import json
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from tests.helpers import HOME, cs, dr, fake_get, fake_gql, reset_home


class Base(unittest.TestCase):
    def setUp(self):
        reset_home()
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("STRATZ_TOKEN", None)


class ConfigTests(Base):
    def test_defaults(self):
        cfg = cs.load_config()
        self.assertEqual((cfg["bracket"], cfg["weeks"], cfg["token"]), ("LEGEND_ANCIENT", 2, ""))

    def test_save_and_clamp_weeks(self):
        cs.save_config(token="abc", weeks=99)
        self.assertEqual(cs.load_config()["token"], "abc")
        self.assertEqual(cs.current_weeks(), cs.MAX_WEEKS)
        cs.save_config(weeks="junk")
        self.assertEqual(cs.current_weeks(), 2)

    def test_token_precedence_and_trimming(self):
        cs.save_config(token="  abc123  ")
        self.assertEqual(cs.get_token(), "abc123")
        os.environ["STRATZ_TOKEN"] = "envtok"
        self.assertEqual(cs.get_token(), "envtok")

    def test_bracket_validation(self):
        self.assertEqual(cs.bracket_ranks("LEGEND_ANCIENT"), ["LEGEND", "ANCIENT"])
        self.assertEqual(cs.bracket_ranks("IMMORTAL"), ["IMMORTAL"])
        for bad in ("LEGEND; DROP", "FOO_BAR", ""):
            with self.assertRaises(cs.StratzError, msg=bad):
                cs.bracket_ranks(bad)
        self.assertEqual(cs.bracket_label("DIVINE_IMMORTAL"), "Divine / Immortal")

    def test_a_bad_bracket_in_config_never_reaches_a_query(self):
        cs.save_config(bracket='LEGEND_ANCIENT) { x } #')
        with mock.patch.object(cs, "gql", fake_gql), self.assertRaises(cs.StratzError):
            cs.fetch(lambda m: None)


class GqlTests(Base):
    @staticmethod
    def _post(status=200, payload=None, exc=None):
        def post(url, json=None, headers=None, timeout=None):
            if exc:
                raise exc
            return SimpleNamespace(status_code=status, json=lambda: payload, text="x")
        return post

    def test_missing_token(self):
        with self.assertRaisesRegex(cs.StratzError, "token"):
            cs.gql("q")

    def test_rejected_token(self):
        with mock.patch.object(cs.requests, "post", self._post(401, {})):
            with self.assertRaisesRegex(cs.StratzError, "rejected"):
                cs.gql("q", token="t")

    def test_graphql_errors_become_messages(self):
        with mock.patch.object(cs.requests, "post", self._post(200, {"errors": [{"message": "Bad thing"}]})):
            with self.assertRaisesRegex(cs.StratzError, "Bad thing"):
                cs.gql("q", token="t")

    def test_network_failure(self):
        with mock.patch.object(cs.requests, "post", self._post(exc=cs.requests.ConnectionError("down"))):
            with self.assertRaisesRegex(cs.StratzError, "Network"):
                cs.gql("q", token="t")


class FetchTests(Base):
    def setUp(self):
        super().setUp()
        self.queries = []

        def recording(query, token=None):
            self.queries.append(query)
            return fake_gql(query)

        patcher = mock.patch.object(cs, "gql", recording)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_matchups_use_the_configured_bracket(self):
        cs.save_config(bracket="DIVINE_IMMORTAL")
        log = []
        cs.fetch(log.append)
        self.assertTrue(any("DIVINE_IMMORTAL" in q for q in self.queries if "matchUp" in q))
        self.assertTrue((cs.CACHE / "matchups.json").exists())
        self.assertEqual(cs.get_info()["matchups"]["bracket"], "DIVINE_IMMORTAL")
        self.assertTrue(any("saved" in m for m in log))

    def test_meta_queries_use_the_matching_individual_ranks(self):
        for bracket, ranks in (("DIVINE_IMMORTAL", "DIVINE, IMMORTAL"), ("LEGEND_ANCIENT", "LEGEND, ANCIENT")):
            self.queries.clear()
            cs.save_config(bracket=bracket)
            cs.fetch_meta(lambda m: None)
            self.assertTrue(all(ranks in q for q in self.queries), bracket)

    def test_changing_weeks_needs_no_download(self):
        cs.fetch_meta(lambda m: None)
        raw = json.loads((cs.CACHE / "meta.json").read_text())
        self.assertEqual((raw["version"], raw["weeks"]), (2, [100, 200, 300, 400]))
        self.queries.clear()
        wins = {}
        for weeks in (1, 2, 4):
            cs.save_config(weeks=weeks)
            wins[weeks] = {h: win for h, win, _, _ in cs.meta_table(1)}[8]
        self.assertAlmostEqual(wins[1], 70, delta=1)
        self.assertAlmostEqual(wins[2], 65, delta=1)
        self.assertAlmostEqual(wins[4], 55, delta=1)
        self.assertEqual(self.queries, [])
        self.assertEqual(cs.meta_weeks_available(), 4)
        self.assertTrue(cs.meta_pool(1))

    def test_older_meta_files_still_load(self):
        cs.CACHE.mkdir(parents=True, exist_ok=True)
        meta = cs.CACHE / "meta.json"
        meta.write_text(json.dumps({"1": {"1": [9000, 4700], "2": [8000, 3900]}}))
        self.assertTrue(cs.meta_table(1) and cs.meta_pool(1))
        self.assertIsNone(cs.meta_weeks_available())
        meta.write_text(json.dumps({"1": {"1": 9000, "2": 8000}}))     # counts only
        self.assertTrue(cs.meta_pool(1))
        with self.assertRaises(ValueError):
            cs.meta_table(1)

    def test_tiny_samples_are_left_out_of_the_first_pick_table(self):
        cs.fetch_meta(lambda m: None)
        shown = {h for h, *_ in cs.meta_table(1)}
        barely_played = {h for h in range(1, 9) if (h + 1) % 4 == 0}      # see fake_gql
        self.assertTrue(barely_played and not (shown & barely_played))


class BracketDiscoveryTests(Base):
    def test_falls_back_without_a_token(self):
        self.assertEqual(cs.available_brackets(), cs.FALLBACK_BRACKETS)

    def test_filters_values_that_are_not_ranks(self):
        names = ("HERALD_GUARDIAN", "LEGEND_ANCIENT", "ALL", "UNCALIBRATED")
        fields = [{"name": "matchUp", "args": [{"name": "bracketBasicIds",
                                                "type": {"name": "RankBracketBasicEnum"}}]}]
        enum = {"__type": {"enumValues": [{"name": n} for n in names]}}
        with mock.patch.object(cs, "_fields", lambda t: fields), \
                mock.patch.object(cs, "gql", lambda q, token=None: enum):
            self.assertEqual(cs.available_brackets(), ["HERALD_GUARDIAN", "LEGEND_ANCIENT", "UNCALIBRATED"])


class PortraitTests(Base):
    def test_download_once_then_only_the_hero_list(self):
        gets, log = [], []

        def counting(url, timeout=None):
            gets.append(url)
            return fake_get(url, timeout)

        with mock.patch.object(dr.requests, "get", counting):
            dr.fetch(log.append)
            self.assertEqual(len(list(dr.PORTRAIT_DIR.glob("[0-9]*.png"))), 8)
            self.assertTrue(dr.HEROES_JSON.exists())
            self.assertTrue(any("Portraits: 8/8" in m for m in log))
            first = len(gets)
            dr.fetch(log.append)
            self.assertEqual(len(gets), first + 1)


if __name__ == "__main__":
    unittest.main()
