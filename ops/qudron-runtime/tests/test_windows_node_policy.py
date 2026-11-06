import tempfile
import sys
import time
import unittest
from pathlib import Path

from windows_node.policy import approval_resource, sign_approval
from windows_node.worker import WindowsNode, WindowsNodeError, PywinautoAutomation


class FakeAutomation:
    def __init__(self):
        self.invocations = []

    def list_windows(self):
        return [{"title": "Notepad", "process_id": 123, "handle": 456}]

    def inspect_window(self, process_id, window_handle):
        return {"title": "Notepad", "process_id": process_id, "handle": window_handle, "controls": [], "control_count": 0}

    def launch_app(self, path):
        self.invocations.append(("launch", path))
        return {"launched": True, "process_id": 99}

    def invoke_control(self, process_id, window_handle, window_title, automation_id, control_type):
        self.invocations.append(("invoke", process_id, window_handle, window_title, automation_id, control_type))
        return {"invoked": True, "automation_id": automation_id}

    def type_text(self, process_id, window_handle, window_title, automation_id, control_type, text):
        self.invocations.append(("type", process_id, window_handle, window_title, automation_id, control_type, text))
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


    def test_inspect_window_is_read_only_and_does_not_require_approval(self):
        result = self.node.execute({
            "task_id": "task-inspect", "idempotency_key": "idem-inspect",
            "action": "windows.inspect_window",
            "parameters": {"process_id": 123, "window_handle": 456},
        })
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"]["title"], "Notepad")
        self.assertEqual(self.automation.invocations, [])

    def test_invoke_control_requires_and_consumes_exact_approval(self):
        params = {
            "process_id": 123, "window_handle": 456, "window_title": "Notepad",
            "automation_id": "search-box", "control_type": "Edit",
        }
        with self.assertRaises(WindowsNodeError):
            self.node.execute({
                "task_id": "task-invoke-denied", "idempotency_key": "idem-invoke-denied",
                "action": "windows.invoke_control", "parameters": params,
            })
        approval = self.approval(
            "windows.invoke_control", params, "nonce-invoke-00000001"
        )
        payload = {
            "task_id": "task-invoke", "idempotency_key": "idem-invoke",
            "action": "windows.invoke_control", "parameters": params,
            "approval": approval,
        }
        result = self.node.execute(payload)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(
            self.automation.invocations,
            [("invoke", 123, 456, "Notepad", "search-box", "Edit")],
        )
        with self.assertRaises(WindowsNodeError):
            self.node.execute({
                **payload,
                "task_id": "task-invoke-replay",
                "idempotency_key": "idem-invoke-replay",
            })

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


    def test_approval_resource_binds_exact_untrimmed_ui_selectors(self):
        base = {
            "process_id": 123, "window_handle": 456, "window_title": "Notepad",
            "automation_id": "search-box", "control_type": "Edit",
        }
        padded = {**base, "automation_id": " search-box "}
        self.assertNotEqual(
            approval_resource("windows.invoke_control", base),
            approval_resource("windows.invoke_control", padded),
        )

    def test_typed_text_is_bound_to_approved_exact_payload(self):
        params = {
            "process_id": 123, "window_handle": 456, "window_title": "Notepad",
            "automation_id": "search", "control_type": "Edit", "text": "approved text",
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

    def test_pywinauto_text_entry_requires_exact_edit_control_and_writes_literal_text(self):
        class FakeControl:
            def __init__(self):
                self.value = None
                self.focused = False
            def exists(self, timeout=0):
                return True
            def set_focus(self):
                self.focused = True
            def set_edit_text(self, value):
                self.value = value

        class FakeWindow:
            def __init__(self, control):
                self.control = control
            handle = 456
            def process_id(self):
                return 123
            def window_text(self):
                return "Notepad"
            def child_window(self, auto_id, control_type):
                self.selector = (auto_id, control_type)
                return self.control

        class FakeDesktop:
            def __init__(self, window):
                self.window = window
            def windows(self):
                return [self.window]

        control = FakeControl()
        window = FakeWindow(control)
        automation = PywinautoAutomation()
        automation._desktop = lambda: FakeDesktop(window)

        literal = "{ENTER} + ^ {TAB}"
        result = automation.type_text(123, 456, "Notepad", "search-box", "Edit", literal)
        self.assertEqual(result["character_count"], len(literal))
        self.assertEqual(control.value, literal)
        self.assertTrue(control.focused)
        self.assertEqual(window.selector, ("search-box", "Edit"))
        with self.assertRaises(WindowsNodeError):
            automation.type_text(123, "Notepad", "", "Edit", "must not type")
        with self.assertRaises(WindowsNodeError):
            automation.type_text(123, "Notepad", "search-box", "Button", "must not type")

    def test_idempotent_ui_action_receipt_survives_worker_restart(self):
        params = {"app_alias": "notepad"}
        approval = self.approval(
            "windows.launch_app", params, "nonce-restart-00000001"
        )
        payload = {
            "task_id": "task-restart", "idempotency_key": "idem-restart",
            "action": "windows.launch_app", "parameters": params,
            "approval": approval,
        }
        first = self.node.execute(payload)
        restarted = WindowsNode(
            token="t" * 40,
            approval_secret="s" * 40,
            database_path=Path(self.temp.name) / "windows.sqlite3",
            allowed_apps={"notepad": "C:/Windows/notepad.exe"},
            automation=self.automation,
        )
        second = restarted.execute(payload)
        self.assertFalse(first["replayed"])
        self.assertTrue(second["replayed"])
        self.assertEqual(len(self.automation.invocations), 1)

    def test_running_receipt_replay_is_unknown_and_never_reexecutes_action(self):
        params = {"app_alias": "notepad"}
        key = "idem-running-unknown"
        with self.node._connect() as db:
            now = time.time()
            db.execute(
                """INSERT INTO task_receipts
                   (idempotency_key,task_id,action,status,created_at,updated_at)
                   VALUES(?,?,?,'running',?,?)""",
                (key, "task-running", "windows.launch_app", now, now),
            )
        result = self.node.execute({
            "task_id": "task-running", "idempotency_key": key,
            "action": "windows.launch_app", "parameters": params,
        })
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["error_code"], "outcome_unknown_requires_reconciliation")
        self.assertTrue(result["reconciliation_required"])
        self.assertTrue(result["replayed"])
        self.assertEqual(self.automation.invocations, [])

    def test_execute_rejects_missing_or_non_string_type_text_selectors(self):
        base = {
            "task_id": "task-invalid-type-text",
            "idempotency_key": "idem-invalid-type-text",
            "action": "windows.type_text",
            "parameters": {
                "process_id": 123, "window_handle": 456, "window_title": "Notepad",
                "automation_id": "search-box", "control_type": "Edit", "text": "literal text",
            },
        }
        for changes in (
            {"window_title": ""},
            {"automation_id": ""},
            {"automation_id": ["not", "a", "string"]},
            {"control_type": "Button"},
            {"text": 123},
            {"process_id": "123"},
        ):
            payload = {**base, "parameters": {**base["parameters"], **changes}}
            with self.subTest(changes=changes):
                with self.assertRaises(WindowsNodeError):
                    self.node.execute(payload)
        self.assertEqual(self.automation.invocations, [])

    def test_health_reports_ui_automation_unavailable_without_windows_backend(self):
        if sys.platform != "win32":
            self.assertFalse(self.node.health()["ui_automation_available"])

    def test_approval_resource_binds_exact_window_title(self):
        base = {
            "process_id": 123,
            "window_handle": 456,
            "window_title": "Notepad - Notes",
            "automation_id": "search-box",
            "control_type": "Edit",
            "text": "literal text",
        }
        first = approval_resource("windows.type_text", base)
        second = approval_resource(
            "windows.type_text", {**base, "window_title": "Another Window"}
        )
        self.assertNotEqual(first, second)
        with self.assertRaisesRegex(ValueError, "window_title"):
            approval_resource("windows.type_text", {**base, "window_title": ""})

    def test_worker_has_no_arbitrary_shell_action(self):
        with self.assertRaises(WindowsNodeError):
            self.node.execute({
                "task_id": "task-7", "idempotency_key": "idem-7",
                "action": "shell.exec", "parameters": {"command": "whoami"},
            })


if __name__ == "__main__":
    unittest.main()
