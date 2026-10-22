import threading
import unittest
from unittest import mock

import numpy as np

import draft_assistant as da
import draft_overlay as ov
import updater
from tests.helpers import build_world, cs, dr, make_frame, overlay_args, reset_home


def text(widget):
    return widget.opts.get("text", "")


class SyncThread:
    """Runs a thread's work immediately, so tests need no waiting."""

    def __init__(self, target=None, daemon=None, **kw):
        self._target = target

    def start(self):
        self._target()


class OverlayTests(unittest.TestCase):
    def setUp(self):
        reset_home()
        build_world()
        cs.save_config(token="", weeks=2, bracket="LEGEND_ANCIENT")
        da.use_slots_file()

    def test_launch_version_has_settings_but_no_snap(self):
        o = ov.Overlay(overlay_args())
        self.assertIn(("team", "settings"), o.buttons)
        self.assertNotIn(("team", "snap"), o.buttons)
        self.assertIn(("team", "snap"), ov.Overlay(overlay_args(dev=True)).buttons)

    def test_footer_names_the_bracket_and_weeks(self):
        o = ov.Overlay(overlay_args())
        self.assertTrue(o.ready)
        self.assertIn("Legend / Ancient", text(o.footer))
        self.assertIn("2 wk meta", text(o.footer))

    def test_reads_a_draft_and_shows_the_counter_table(self):
        frame = make_frame({"radiant_1": 1, "radiant_2": 2, "radiant_3": 3, "dire_1": 4, "dire_2": 5})
        o = ov.Overlay(overlay_args())
        o.on_button("me", 3)                                       # I am radiant_3
        with mock.patch.object(da, "grab", lambda monitor: frame):
            o.tick()
            o.tick()
        self.assertEqual(text(o.ally_lbl), "Allies: Hero1, Hero2")
        self.assertEqual(text(o.enemy_lbl), "Enemies: Hero4, Hero5")
        self.assertFalse(text(o.title).startswith("error"))
        self.assertEqual(o.cols.opts["text"], ov.COUNTER_COLS)
        self.assertTrue(text(o.rows[0]))

    def test_nothing_picked_shows_the_first_pick_table(self):
        o = ov.Overlay(overlay_args())
        o.on_button("position", 1)
        self.assertIn("No picks yet", text(o.title))
        self.assertEqual(o.cols.opts["text"], ov.META_COLS)
        self.assertTrue(text(o.rows[0]))

    def test_choices_are_remembered_and_flags_still_win(self):
        o = ov.Overlay(overlay_args())
        o.on_button("team", "dire")
        o.on_button("position", 1)
        o.on_button("position", "toggle")
        o.on_button("me", 3)
        again = ov.Overlay(overlay_args())
        self.assertEqual((again.team, again.position, again.meta, again.me_idx), ("dire", 1, True, 3))
        self.assertEqual(ov.Overlay(overlay_args(team="radiant", position=4)).position, 4)

    def test_the_pool_cache_depends_on_the_weeks_setting(self):
        o = ov.Overlay(overlay_args(position=1))
        o.pool()
        cs.save_config(weeks=1)
        o.pool()
        self.assertEqual({key[2] for key in o.pools}, {2, 1})

    def test_missing_position_data_gives_a_helpful_message(self):
        (cs.CACHE / "meta.json").unlink()
        o = ov.Overlay(overlay_args(position=1))
        o.render({})
        self.assertIn("position data", text(o.title))


class SettingsTests(unittest.TestCase):
    def setUp(self):
        reset_home()
        build_world()
        cs.save_config(token="", weeks=2, bracket="LEGEND_ANCIENT")
        for patcher in (mock.patch.object(threading, "Thread", SyncThread),
                        mock.patch.object(cs, "available_brackets",
                                          lambda: ["HERALD_GUARDIAN", "LEGEND_ANCIENT", "DIVINE_IMMORTAL"])):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.o = ov.Overlay(overlay_args())
        self.o.open_settings()
        self.sw = self.o.settings

    def test_opens_with_saved_values_and_is_reused(self):
        self.assertEqual((self.sw.bracket_var.get(), self.sw.weeks_var.get()), ("Legend / Ancient", "2"))
        self.o.open_settings()
        self.assertIs(self.o.settings, self.sw)

    def test_save_writes_trimmed_token_bracket_and_weeks(self):
        self.sw.token_var.set("  my-secret  ")
        self.sw.bracket_var.set("Divine / Immortal")
        self.sw.weeks_var.set("3")
        self.sw.save()
        cfg = cs.load_config()
        self.assertEqual((cfg["token"], cfg["bracket"], cfg["weeks"]), ("my-secret", "DIVINE_IMMORTAL", 3))
        self.assertIn("Bracket changed", text(self.o.footer))
        self.assertEqual(self.sw.status_labels["matchups"].opts["fg"], ov.STATE_COLOUR["stale"])

    def test_bad_weeks_input_is_handled(self):
        self.sw.weeks_var.set("3")
        self.sw.save()
        self.sw.weeks_var.set("banana")
        self.sw.save()
        self.assertEqual((cs.load_config()["weeks"], self.sw.weeks_var.get()), (3, "3"))
        self.sw.weeks_var.set("500")
        self.sw.save()
        self.assertEqual(cs.load_config()["weeks"], cs.MAX_WEEKS)

    def test_unknown_bracket_label_keeps_the_saved_bracket(self):
        self.sw.bracket_var.set("")
        self.sw.save()
        self.assertEqual(cs.load_config()["bracket"], "LEGEND_ANCIENT")

    def test_update_flow_disables_buttons_and_ignores_double_clicks(self):
        seen = {}

        def fake_run(tasks, progress):
            seen["tasks"] = list(tasks)
            progress("Matchups: 8/8 heroes")
            return [(t, True, "ok") for t in tasks]

        with mock.patch.object(updater, "run", fake_run):
            self.sw.start(["matchups", "meta"])
            self.assertTrue(self.sw.busy)
            self.assertEqual(self.sw.task_buttons["meta"].opts["state"], "disabled")
            self.sw.start(["portraits"])                           # ignored
            self.assertEqual(seen["tasks"], ["matchups", "meta"])
            self.sw.poll()                                         # worker results arrive via the queue
        self.assertFalse(self.sw.busy)
        self.assertEqual(self.sw.task_buttons["meta"].opts["state"], "normal")

    def test_failed_update_still_reloads_the_overlay(self):
        results = [("matchups", False, "Stratz rejected the token (HTTP 401)."), ("meta", False, "same")]
        reloads = []
        real_load = self.o.load_data
        self.o.load_data = lambda: (reloads.append(1), real_load())[1]
        with mock.patch.object(updater, "run", lambda tasks, progress: results):
            self.sw.start(["matchups", "meta"])
            self.sw.poll()
        self.assertTrue(reloads)
        self.assertFalse(self.sw.busy)

    def test_closing_mid_update_is_safe(self):
        reloads = []
        real_load = self.o.load_data
        self.o.load_data = lambda: (reloads.append(1), real_load())[1]
        with mock.patch.object(updater, "run", lambda tasks, progress: [(t, True, "ok") for t in tasks]):
            self.sw.start(["matchups"])
            self.sw.close()
            self.assertIsNone(self.o.settings)
            self.sw.poll()
        self.assertTrue(reloads)


class FirstRunTests(unittest.TestCase):
    def setUp(self):
        reset_home()

    def test_no_data_means_setup_message_and_settings_opens_itself(self):
        o = ov.Overlay(overlay_args())
        self.assertFalse(o.ready)
        self.assertIn("No data yet", text(o.footer))
        o.tick()
        self.assertIn("Setup needed", text(o.title))
        o.run()
        scheduled = [fn for _, fn in o.root.afters]
        self.assertIn(o.open_settings, scheduled)
        self.assertIn(o.tick, scheduled)
        self.assertIn(o.keep_on_top, scheduled)
        o.open_settings()
        statuses = [label.opts["text"] for label in o.settings.status_labels.values()]
        self.assertEqual(statuses, ["Not downloaded yet"] * 3)


if __name__ == "__main__":
    unittest.main()
