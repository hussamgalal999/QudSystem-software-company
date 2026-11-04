import unittest

from telegram_gateway import format_status, format_usage, parse_command, parse_owner_ids


class TelegramGatewayTests(unittest.TestCase):
    def test_owner_allowlist_parses_and_ignores_empty_values(self):
        self.assertEqual(parse_owner_ids("123, 456,, "), {"123", "456"})

    def test_commands_strip_bot_suffix_and_parse_argument(self):
        self.assertEqual(parse_command("/status@QudronBot"), ("/status", ""))
        self.assertEqual(parse_command("/task research the local market"), ("/task", "research the local market"))

    def test_status_output_is_bounded_and_does_not_include_internal_paths(self):
        result = format_status({
            "counts": {"pending": 2, "running": 1, "completed": 4},
            "latest_jobs": [{"title": "Market scan", "status": "completed", "result_path": "/secret/path"}],
        })
        self.assertIn("pending: 2", result)
        self.assertIn("Market scan [completed]", result)
        self.assertNotIn("/secret/path", result)

    def test_usage_output_reports_known_cost_only(self):
        result = format_usage({
            "daily": {"calls": 3, "total_tokens": 900, "cost_usd": 0.01},
            "monthly": {"calls": 10, "total_tokens": 3000, "cost_usd": 0.04},
        })
        self.assertIn("daily: calls=3", result)
        self.assertIn("known_cost_usd=0.04", result)


if __name__ == "__main__":
    unittest.main()
