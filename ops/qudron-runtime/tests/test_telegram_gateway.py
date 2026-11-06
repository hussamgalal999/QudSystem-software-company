import unittest
from unittest.mock import Mock, patch

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

    def test_unapproved_internal_url_fails_before_network(self):
        import os
        from telegram_gateway import TelegramGateway
        with patch.dict(os.environ, {"QUDRON_INTERNAL_URL": "http://qudron.attacker:8765"}, clear=False):
            with self.assertRaisesRegex(ValueError, "QUDRON_INTERNAL_URL"):
                TelegramGateway()

    def test_request_rejects_unapproved_target_before_network(self):
        from telegram_gateway import TelegramGateway
        gateway = TelegramGateway()
        with patch("telegram_gateway.open_credential_request") as opener:
            with self.assertRaisesRegex(ValueError, "not an approved service"):
                gateway._request("https://attacker.example/collect", headers={"Authorization": "Bearer test"})
            opener.assert_not_called()

    def test_non_owner_messages_are_ignored(self):
        from telegram_gateway import TelegramGateway
        gateway = TelegramGateway()
        gateway.owner_ids = {"111"}
        gateway.send = Mock()
        gateway.handle_update({
            "update_id": 10,
            "message": {"chat": {"id": 222, "type": "private"}, "from": {"id": 222}, "text": "/status"},
        })
        gateway.send.assert_not_called()

    def test_group_chat_is_rejected_even_if_chat_id_is_allowlisted(self):
        from telegram_gateway import TelegramGateway
        gateway = TelegramGateway()
        gateway.owner_ids = {"-100111"}
        gateway.send = Mock()
        gateway.handle_update({"update_id": 11, "message": {"chat": {"id": -100111, "type": "supergroup"}, "from": {"id": 111}, "text": "/status"}})
        gateway.send.assert_not_called()

    def test_private_chat_sender_must_match_allowlisted_owner(self):
        from telegram_gateway import TelegramGateway
        gateway = TelegramGateway()
        gateway.owner_ids = {"111"}
        gateway.send = Mock()
        gateway.handle_update({"update_id": 12, "message": {"chat": {"id": 111, "type": "private"}, "from": {"id": 222}, "text": "/status"}})
        gateway.send.assert_not_called()

    def test_owner_task_command_uses_update_id_for_idempotency(self):
        from telegram_gateway import TelegramGateway
        gateway = TelegramGateway()
        gateway.owner_ids = {"111"}
        gateway.send = Mock()
        gateway.enqueue_research = Mock(return_value={
            "created": True, "job": {"id": "job-123", "status": "pending"}
        })
        gateway.handle_update({
            "update_id": 42,
            "message": {"chat": {"id": 111, "type": "private"}, "from": {"id": 111}, "text": "/task research Minya market"},
        })
        gateway.enqueue_research.assert_called_once_with(42, "research Minya market")
        gateway.send.assert_called_once()
        self.assertIn("job-123", gateway.send.call_args.args[1])


    def test_completed_report_notification_is_persistently_deduplicated(self):
        import tempfile
        from pathlib import Path
        from telegram_gateway import TelegramGateway
        with tempfile.TemporaryDirectory() as tmp:
            gateway = TelegramGateway()
            gateway.notification_db_path = Path(tmp) / "notifications.sqlite3"
            gateway.owner_ids = {"111"}
            gateway.qudron = Mock(return_value={"latest_jobs": [{
                "id": "job-abc", "title": "Research report", "status": "completed", "result_available": True
            }]})
            gateway.qudron_result_text = Mock(return_value="# Verified report\nFindings")
            gateway.send = Mock()
            self.assertEqual(gateway.poll_completion_notifications(), 1)
            self.assertEqual(gateway.poll_completion_notifications(), 0)
            gateway.send.assert_called_once()
            self.assertIn("Verified report", gateway.send.call_args.args[1])

    def test_failed_task_notification_hides_internal_error_details(self):
        import tempfile
        from pathlib import Path
        from telegram_gateway import TelegramGateway
        with tempfile.TemporaryDirectory() as tmp:
            gateway = TelegramGateway()
            gateway.notification_db_path = Path(tmp) / "notifications.sqlite3"
            gateway.owner_ids = {"111"}
            gateway.qudron = Mock(return_value={"latest_jobs": [{
                "id": "job-failed", "title": "Research task", "status": "failed", "error": "private provider detail"
            }]})
            gateway.send = Mock()
            self.assertEqual(gateway.poll_completion_notifications(), 1)
            self.assertIn("failed", gateway.send.call_args.args[1])
            self.assertNotIn("private provider detail", gateway.send.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
