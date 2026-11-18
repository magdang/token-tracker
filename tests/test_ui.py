import unittest

from token_tracker.ui import observed_at


class TimestampTests(unittest.TestCase):
    def test_missing(self):
        self.assertEqual(observed_at(None), "Not yet updated")

    def test_invalid(self):
        self.assertEqual(observed_at("not-a-date"), "Unknown observation time")

    def test_naive(self):
        self.assertEqual(observed_at("2026-11-18T12:00:00"), "Timestamp needs a timezone")

    def test_aware(self):
        self.assertIn("Observed", observed_at("2026-11-18T12:00:00Z"))
