import unittest
from concurrent.futures import Future
from unittest.mock import Mock, patch

from token_tracker.core import Metric, Snapshot
from token_tracker.ui import Gdk, Overlay, REFRESH_SECONDS, metric_value, observed_at, reset_text


class InteractionTests(unittest.TestCase):
    def test_child_crossing_is_ignored_and_escape_dismisses(self):
        overlay = Mock()
        Overlay.crossing(overlay, None, Mock(detail=Gdk.NotifyType.INFERIOR), "panel", False)
        overlay.hover.leave.assert_not_called()
        self.assertTrue(Overlay.key_pressed(overlay, None, Mock(keyval=Gdk.KEY_Escape)))
        overlay.hover.dismiss.assert_called_once()

    def test_open_pins_panel_to_launcher_monitor(self):
        overlay = Mock()
        overlay.window.get_visible.return_value = False
        with patch("token_tracker.ui.Gdk.Display.get_default") as display, \
                patch("token_tracker.ui.GtkLayerShell.set_monitor") as pin:
            Overlay.open_panel(overlay)
        display.return_value.get_monitor_at_window.assert_called_once_with(overlay.launcher.get_window())
        pin.assert_called_once_with(overlay.window, display.return_value.get_monitor_at_window.return_value)
        overlay.window.show_all.assert_called_once()


class TimestampTests(unittest.TestCase):
    def test_missing(self):
        self.assertEqual(observed_at(None), "Not yet updated")

    def test_invalid(self):
        self.assertEqual(observed_at("not-a-date"), "Unknown observation time")

    def test_nontext_timestamp(self):
        self.assertEqual(observed_at(42), "Unknown observation time")

    def test_naive(self):
        self.assertEqual(observed_at("2026-11-18T12:00:00"), "Timestamp needs a timezone")

    def test_aware(self):
        self.assertIn("Observed", observed_at("2026-11-18T12:00:00Z"))

    def test_naive_reset(self):
        self.assertEqual(reset_text("2026-11-18T12:00:00"), "Reset time needs a timezone")

    def test_budget_format(self):
        self.assertEqual(metric_value(Metric("Budget", 12.4, 30, "USD")), "$17.60 left in budget")

    def test_percentage(self):
        self.assertEqual(metric_value(Metric("Weekly", 42)), "58% left")


class PollingTests(unittest.TestCase):
    def test_five_second_refresh_even_when_collapsed(self):
        overlay = Mock()
        self.assertEqual(REFRESH_SECONDS, 5)
        self.assertTrue(Overlay.tick(overlay))
        overlay.refresh.assert_called_once()

    def test_slow_account_does_not_block_other_accounts(self):
        overlay = Overlay()
        overlay.render = Mock()
        overlay.pool.shutdown(wait=False)
        overlay.pool = Mock()
        overlay.pool.submit.return_value = Future()
        accounts = [
            {"id": "slow", "name": "Slow", "provider": "manual"},
            {"id": "ready", "name": "Ready", "provider": "manual"},
        ]
        overlay.pending["slow"] = accounts[0]
        with patch("token_tracker.ui.load_accounts", return_value=accounts):
            overlay.refresh()
        self.assertEqual(overlay.pool.submit.call_count, 1)
        self.assertEqual(overlay.pool.submit.call_args.args[1]["id"], "ready")

    def test_failure_keeps_last_good_data_and_backs_off(self):
        overlay = Overlay()
        overlay.render = Mock()
        account = {"id": "one", "name": "One", "provider": "manual"}
        overlay.accounts = [account]
        overlay.pending["one"] = account
        overlay.results["one"] = Snapshot("one", "reported", "2026-11-18T12:00:00Z", [Metric("Usage", 42)])
        with patch("token_tracker.ui.monotonic", return_value=100):
            overlay.received(account, Snapshot("one", "unavailable", error="HTTP 429"))
        self.assertEqual(overlay.results["one"].metrics[0].used, 42)
        self.assertEqual(overlay.results["one"].source, "stale")
        self.assertEqual(overlay.retry_after["one"], 110)
        overlay.pool.shutdown(wait=False)

    def test_reconfigured_account_discards_old_result(self):
        overlay = Overlay()
        overlay.render = Mock()
        old = {"id": "one", "name": "Old", "provider": "manual"}
        overlay.pending["one"] = old
        overlay.accounts = [{**old, "name": "New"}]
        overlay.received(old, Snapshot("one", "reported"))
        self.assertNotIn("one", overlay.results)
        overlay.pool.shutdown(wait=False)

    def test_config_changes_clear_cached_state_without_overlapping_requests(self):
        overlay = Overlay()
        self.addCleanup(overlay.pool.shutdown, wait=False)
        overlay.render = Mock()
        overlay.pool.submit = Mock(return_value=Future())
        old = {"id": "one", "name": "Old", "provider": "manual"}
        new = {**old, "name": "New"}
        overlay.accounts = [old]
        overlay.pending["one"] = old
        overlay.results["one"] = Snapshot("one", "reported", metrics=[Metric("Old", 42)])
        overlay.failures["one"] = 6
        overlay.retry_after["one"] = float("inf")
        with patch("token_tracker.ui.load_accounts", return_value=[new]):
            overlay.refresh()
        self.assertFalse(overlay.results)
        self.assertFalse(overlay.failures)
        self.assertFalse(overlay.retry_after)
        overlay.pool.submit.assert_not_called()
        # Even switching back cannot make the invalidated request current again.
        with patch("token_tracker.ui.load_accounts", return_value=[old]):
            overlay.refresh()
            overlay.received(old, Snapshot("one", "reported"))
            self.assertFalse(overlay.results)
            overlay.refresh()
        overlay.pool.submit.assert_called_once()
        with patch("token_tracker.ui.load_accounts", return_value=[]):
            overlay.refresh()
        overlay.received(old, Snapshot("one", "reported"))
        self.assertFalse(overlay.results)
        self.assertFalse(overlay.pending)

    def test_backoff_skips_failed_account_only_and_caps_at_five_minutes(self):
        overlay = Overlay()
        self.addCleanup(overlay.pool.shutdown, wait=False)
        overlay.render = Mock()
        overlay.pool.submit = Mock(return_value=Future())
        accounts = [{"id": identity, "name": identity, "provider": "manual"}
                    for identity in ("failed", "ready")]
        overlay.accounts = accounts
        overlay.failures["failed"] = 6
        overlay.pending["failed"] = accounts[0]
        with patch("token_tracker.ui.monotonic", return_value=100):
            overlay.received(accounts[0], Snapshot("failed", "unavailable", error="Offline"))
            self.assertEqual(overlay.retry_after["failed"], 400)
            with patch("token_tracker.ui.load_accounts", return_value=accounts):
                overlay.refresh()
        self.assertEqual(overlay.pool.submit.call_args.args[1]["id"], "ready")
        overlay.pool.submit.assert_called_once()

    def test_invalid_config_can_recover(self):
        overlay = Overlay()
        self.addCleanup(overlay.pool.shutdown, wait=False)
        overlay.render = Mock()
        with patch("token_tracker.ui.load_accounts", side_effect=ValueError):
            overlay.refresh()
        self.assertIsNotNone(overlay.config_error)
        with patch("token_tracker.ui.load_accounts", return_value=[]):
            overlay.refresh()
        self.assertIsNone(overlay.config_error)
