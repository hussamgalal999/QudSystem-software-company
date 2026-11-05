import tempfile
import time
import unittest
from pathlib import Path

from windows_node.policy import approval_resource, sign_approval
from windows_node.worker import WindowsNode, WindowsNodeError


class FakeAutomation:
    def __init__(self):
        self.invocations = []

    def list_windows(self):
        return [{"title": "Notepad", "process_id": 123}]

    def inspect_window(self, process_id):
        return {"title": "Notepad", "process_id": process_id, "controls": [], "control_count": 0}

    def launch_app(self, path):
        self.invocations.append(("launch", path))
        return {"launched": True, "process_id": 99}

    def invoke_control(self, process_id, automation_id, control_type):
        self.invocations.append(("invoke", process_id, automation_id, control_type))
        return {"invoked": True, "automation_id": automation_id}

    def type_text(self, process_id, automation_id, control_type, text):
        self.invocations.append(("type", process_id, automation_id, control_type, text))
        return {"typed": True, "character_count": len(text)}


class WindowsNodePolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.automation = FakeAutomation()
        self.node = WindowsNode(
            token="t" * 40,
            approval_secret="s" * 40,
            database_path=Path(self.temp.name) / "windows.sqlite3",
            allowed_apps={"notepad": "C:/Windows/notepad.exe"},
            automation=self.automation,
        )

    def tearDown(self):
        self.temp.cleanup()

    def approval(self, action, params, nonce):
        return sign_approval(
            "s" * 40, approver="owner", action=action,
            resource=approval_resource(action, params),
            expires_at=int(time.time()) + 300, nonce=nonce,
        )

    def test_read_only_inspection_needs_no_write_approval(self):
        result = self.node.execute({
            "task_id": "task-1", "idempotency_key": "idem-1",
            "action": "windows.list_windows", "parameters": {},
        })
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"]["windows"][0]["process_id"], 123)

    def test_write_action_requires_signed_approval(self):
        params = {"app_alias": "notepad"}
        with self.assertRaises(WindowsNodeError):
            self.node.execute({
                "task_id": "task-2", "idempotency_key": "idem-2",
                "action": "windows.launch_app", "parameters": params,
            })
        self.assertEqual(self.automation.invocations, [])

    def test_write_action_is_allowed_once_and_idempotent_on_retry(self):
        params = {"app_alias": "notepad"}
        approval = self.approval("windows.launch_app", params, "nonce-00000000000001")
        payload = {
            "task_id": "task-3", "idempotency_key": "idem-3",
            "action": "windows.launch_app", "parameters": params,
            "approval": approval,
        }
        first = self.node.execute(payload)
        second = self.node.execute(payload)
        self.assertFalse(first["replayed"])
        self.assertTrue(second["replayed"])
        self.assertEqual(len(self.automation.invocations), 1)

    def test_approval_cannot_be_replayed_for_a_different_task(self):
        params = {"app_alias": "notepad"}
        approval = self.approval("windows.launch_app", params, "nonce-00000000000002")
        one = {
            "task_id": "task-4", "idempotency_key": "idem-4",
            "action": "windows.launch_app", "parameters": params, "approval": approval,
        }
        two = {
            "task_id": "task-5", "idempotency_key": "idem-5",
            "action": "windows.launch_app", "parameters": params, "approval": approval,
        }
        self.node.execute(one)
        with self.assertRaises(WindowsNodeError):
            self.node.execute(two)
        self.assertEqual(len(self.automation.invocations), 1)

    def test_typed_text_is_bound_to_approved_exact_payload(self):
        params = {
            "process_id": 123, "automation_id": "search",
            "control_type": "Edit", "text": "approved text",
        }
        approval = self.approval("windows.type_text", params, "nonce-00000000000003")
        changed = {**params, "text": "different text"}
        with self.assertRaises(WindowsNodeError):
            self.node.execute({
                "task_id": "task-6", "idempotency_key": "idem-6",
                "action": "windows.type_text", "parameters": changed,
                "approval": approval,
            })
        self.assertEqual(self.automation.invocations, [])

    def test_worker_has_no_arbitrary_shell_action(self):
        with self.assertRaises(WindowsNodeError):
            self.node.execute({
                "task_id": "task-7", "idempotency_key": "idem-7",
                "action": "shell.exec", "parameters": {"command": "whoami"},
            })


if __name__ == "__main__":
    unittest.main()
