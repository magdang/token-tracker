import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from token_tracker.core import fetch, load_accounts, openai_costs, save_accounts, validate


class CoreTests(unittest.TestCase):
    def test_round_trip_and_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config/accounts.json"
            accounts = [{"id": "one", "name": "Personal", "provider": "manual"}]
            save_accounts(accounts, path)
            self.assertEqual(load_accounts(path), accounts)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_multiple_same_provider(self):
        accounts = [
            {"id": identity, "name": identity, "provider": "manual"}
            for identity in ("personal", "work")
        ]
        self.assertEqual(len(validate(accounts)), 2)
        with self.assertRaises(ValueError):
            validate([accounts[0], accounts[0]])

    def test_invalid_numbers(self):
        for budget in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                validate([{"id": "a", "name": "A", "provider": "openai-api", "budget": budget}])

    @patch("token_tracker.core.keyring", return_value="not-a-real-key")
    @patch("token_tracker.core.get_cost_page")
    def test_paginated_costs(self, request, keyring):
        request.side_effect = [
            {"data": [{"results": [{"amount": {"value": 1.1, "currency": "usd"}}]}],
             "has_more": True, "next_page": "next"},
            {"data": [{"results": [{"amount": {"value": 2.2, "currency": "usd"}}]}],
             "has_more": False},
        ]
        result = openai_costs({"id": "a", "budget": 10, "project_id": "proj_test"})
        self.assertEqual(result.metrics[0].used, 3.3)
        self.assertEqual(result.metrics[0].limit, 10)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args.args[0]["project_ids"], ["proj_test"])

    @patch("token_tracker.core.keyring", return_value="secret")
    @patch("token_tracker.core.get_cost_page")
    def test_pagination_cycle_is_not_partial_success(self, request, keyring):
        request.return_value = {"data": [], "has_more": True, "next_page": "same"}
        result = fetch({"id": "a", "provider": "openai-api"})
        self.assertIsNotNone(result.error)
        self.assertFalse(result.metrics)

    def test_missing_codex_data_is_unknown_not_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            result = fetch({"id": "a", "provider": "codex-local", "codex_home": directory})
        self.assertEqual(result.source, "unavailable")
        self.assertEqual(result.metrics, [])

    def test_codex_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            sessions = Path(directory) / "sessions"
            sessions.mkdir()
            event = {
                "timestamp": "2026-11-18T10:00:00Z",
                "payload": {"type": "token_count", "rate_limits": {
                    "primary": {"used_percent": 42, "window_minutes": 300, "resets_at": 1800000000}
                }},
            }
            (sessions / "test.jsonl").write_text("invalid\n" + json.dumps(event) + "\n")
            result = fetch({"id": "a", "provider": "codex-local", "codex_home": directory})
        self.assertEqual(result.metrics[0].used, 42)
        self.assertEqual(result.metrics[0].label, "5h window")
        self.assertEqual(result.updated_at, "2026-11-18T10:00:00+00:00")

    def test_manual_without_data(self):
        result = fetch({"id": "a", "provider": "manual"})
        self.assertEqual(result.source, "manual")
        self.assertFalse(result.metrics)


if __name__ == "__main__":
    unittest.main()
