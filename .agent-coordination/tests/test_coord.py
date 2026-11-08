"""Focused tests for the dual-agent coordination board.

Run only these tests (nothing else in the repository is touched):

    python -m unittest discover -s "C:\\Users\\Hossam Galal\\Desktop\\Qudron\\.agent-coordination\\tests" -v

Every test builds its own board inside a temporary directory and always passes
``--root``, so the live board in ``.agent-coordination`` is never written and no
module under ``ops/`` is imported.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
BOARD_DIR = os.path.dirname(HERE)
COORD = os.path.join(BOARD_DIR, "coord.py")
REPO_ROOT = os.path.dirname(BOARD_DIR)
BASE_SHA = "847485ebf07f8f258397eda9dda21018b1259f24"
QODER_WT = "C:/Users/Hossam Galal/Desktop/Qudron"
COPILOT_WT = (
    "C:/Users/Hossam Galal/copilot-worktrees/Qudron/hussamgalal999-cautious-journey"
)


class BoardTestCase(unittest.TestCase):
    """Base fixture: an isolated board directory plus CLI helpers."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="coord-test-")
        self.root = os.path.join(self._tmp, "board-root")
        os.makedirs(self.root, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    # -- CLI helpers -------------------------------------------------------
    def coord(self, *args, cwd=None):
        return subprocess.run(
            [sys.executable, COORD, "--root", self.root] + [str(item) for item in args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd or self.root,
            timeout=180,
        )

    def ok(self, *args, cwd=None):
        proc = self.coord(*args, cwd=cwd)
        self.assertEqual(
            proc.returncode,
            0,
            "expected success for %s\nstdout:\n%s\nstderr:\n%s"
            % (args, proc.stdout, proc.stderr),
        )
        return proc

    def fails(self, code, *args, cwd=None):
        proc = self.coord(*args, cwd=cwd)
        self.assertEqual(
            proc.returncode,
            code,
            "expected exit %d for %s\nstdout:\n%s\nstderr:\n%s"
            % (code, args, proc.stdout, proc.stderr),
        )
        return proc

    def error_code(self, proc):
        try:
            return json.loads(proc.stderr)["error"]
        except (ValueError, KeyError):
            self.fail("stderr is not a coordination error: %r" % proc.stderr)

    def gate_codes(self, proc):
        return {item["code"] for item in json.loads(proc.stdout)["reasons"]}

    def board_json(self):
        return json.loads(self.ok("--json", "board").stdout)

    def events(self):
        path = os.path.join(self.root, "events.jsonl")
        with open(path, "r", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]

    # -- fixture steps -----------------------------------------------------
    def init(self):
        self.ok("init", "--by", "qoder")

    def register(self, agent, worktree, branch="main", base_sha=BASE_SHA):
        return self.ok(
            "register",
            "--agent",
            agent,
            "--no-auto-git",
            "--branch",
            branch,
            "--worktree",
            worktree,
            "--base-sha",
            base_sha,
            "--display-name",
            agent,
            "--role",
            "tester",
        )

    def both_agents(self):
        self.init()
        self.register("qoder", QODER_WT)
        self.register("copilot", COPILOT_WT)


class TestInitAndVerify(BoardTestCase):
    def test_init_creates_layout_and_is_idempotent(self):
        self.init()
        for relative in ("events.jsonl", "board/BOARD.md", "board/HEAD.json", "locks", "tests"):
            self.assertTrue(
                os.path.exists(os.path.join(self.root, relative)), "missing %s" % relative
            )
        self.assertIn("OK", self.ok("verify").stdout)
        self.assertIn("already initialised", self.ok("init", "--by", "qoder").stdout)
        events = self.events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "board.initialized")
        self.assertEqual(events[0]["prev_hash"], "sha256:" + "0" * 64)
        self.assertEqual(events[0]["seq"], 1)

    def test_commands_require_initialisation(self):
        proc = self.fails(2, "board")
        self.assertEqual(self.error_code(proc), "BOARD_NOT_INITIALIZED")

    def test_unknown_plan_is_reported(self):
        self.both_agents()
        proc = self.fails(2, "plan", "ack", "--agent", "copilot", "--plan", "P-9999")
        self.assertEqual(self.error_code(proc), "PLAN_NOT_FOUND")


class TestIdentity(BoardTestCase):
    def setUp(self):
        super().setUp()
        self.init()

    def test_register_records_branch_worktree_and_base_sha(self):
        self.register("qoder", QODER_WT)
        agent = self.board_json()["agents"]["qoder"]
        self.assertEqual(agent["branch"], "main")
        self.assertEqual(agent["worktree"], QODER_WT)
        self.assertEqual(agent["base_sha"], BASE_SHA)
        self.assertEqual(agent["revision"], 1)
        self.assertTrue(agent["registered_at"])

    def test_register_requires_identity_fields(self):
        proc = self.fails(2, "register", "--agent", "qoder", "--no-auto-git")
        self.assertEqual(self.error_code(proc), "MISSING_IDENTITY")

    def test_invalid_agent_id_is_rejected(self):
        proc = self.fails(2, "register", "--agent", "Qoder Agent!", "--no-auto-git")
        self.assertEqual(self.error_code(proc), "INVALID_AGENT_ID")

    def test_reregister_bumps_revision_and_warns_about_base_divergence(self):
        self.register("qoder", QODER_WT)
        proc = self.register("copilot", COPILOT_WT, base_sha="0" * 40)
        self.assertIn("WARNING", proc.stdout)
        self.assertEqual(self.board_json()["agents"]["copilot"]["revision"], 1)
        self.register("copilot", COPILOT_WT)
        self.assertEqual(self.board_json()["agents"]["copilot"]["revision"], 2)
        self.assertEqual(self.board_json()["agents"]["copilot"]["base_sha"], BASE_SHA)

    @unittest.skipUnless(shutil.which("git"), "git executable is required")
    def test_register_auto_detects_git_metadata(self):
        self.ok("register", "--agent", "qoder", cwd=REPO_ROOT)
        agent = self.board_json()["agents"]["qoder"]
        self.assertTrue(agent["branch"])
        self.assertEqual(len(agent["base_sha"]), 40)
        self.assertTrue(agent["worktree"])


class TestPlanFlow(BoardTestCase):
    def setUp(self):
        super().setUp()
        self.both_agents()

    def propose(self, tasks=None):
        tasks = tasks or [
            {
                "id": "T1",
                "owner": "qoder",
                "title": "build coordination infrastructure",
                "files": [".agent-coordination/coord.py"],
            }
        ]
        return self.ok(
            "plan",
            "propose",
            "--agent",
            "qoder",
            "--title",
            "Task 3 coordination",
            "--summary",
            "shared board",
            "--scope",
            ".agent-coordination",
            "--task-json",
            json.dumps(tasks[0]),
            *(["--task-json", json.dumps(tasks[1])] if len(tasks) > 1 else [])
        )

    def test_plan_requires_peer_ack(self):
        self.propose()
        self.assertEqual(self.board_json()["plans"]["P-0001"]["status"], "proposed")
        out = self.ok("plan", "ack", "--agent", "copilot", "--plan", "P-0001").stdout
        self.assertIn("fully acknowledged", out)
        self.assertEqual(self.board_json()["plans"]["P-0001"]["status"], "acked")

    def test_self_ack_is_forbidden(self):
        self.propose()
        proc = self.fails(2, "plan", "ack", "--agent", "qoder", "--plan", "P-0001")
        self.assertEqual(self.error_code(proc), "SELF_ACK_FORBIDDEN")

    def test_task_split_is_persisted(self):
        self.propose(
            [
                {"id": "T1", "owner": "qoder", "title": "infra", "files": ["a.py"]},
                {"id": "T2", "owner": "copilot", "title": "register", "files": ["b.py"]},
            ]
        )
        tasks = self.board_json()["plans"]["P-0001"]["tasks"]
        self.assertEqual([task["id"] for task in tasks], ["T1", "T2"])
        self.assertEqual(tasks[1]["owner"], "copilot")
        self.assertEqual(tasks[1]["status"], "pending")

    def test_rejection_blocks_the_gate(self):
        self.propose()
        self.ok("plan", "reject", "--agent", "copilot", "--plan", "P-0001", "--reason", "too wide")
        self.ok("reserve", "--agent", "qoder", "--plan", "P-0001", "--files", "a.py")
        proc = self.fails(
            3, "--json", "gate", "--agent", "qoder", "--plan", "P-0001", "--files", "a.py"
        )
        self.assertIn("PLAN_REJECTED", self.gate_codes(proc))


class TestReservations(BoardTestCase):
    def setUp(self):
        super().setUp()
        self.both_agents()

    def test_same_path_conflict_is_denied_and_audited(self):
        self.ok("reserve", "--agent", "qoder", "--files", "src/app.py")
        proc = self.fails(3, "reserve", "--agent", "copilot", "--files", "src/app.py")
        self.assertIn("DENIED", proc.stdout)
        self.assertIn("qoder", proc.stdout)
        self.assertEqual(len(self.board_json()["denials"]), 1)

    def test_directory_prefix_counts_as_conflict(self):
        self.ok("reserve", "--agent", "qoder", "--files", "src/lib/")
        proc = self.fails(3, "reserve", "--agent", "copilot", "--files", "src/lib/parser.py")
        self.assertIn("conflict", proc.stdout)

    def test_path_normalisation_unifies_windows_spellings(self):
        self.ok("reserve", "--agent", "qoder", "--files", "./Src\\App.py")
        proc = self.fails(3, "reserve", "--agent", "copilot", "--files", "src/app.py")
        self.assertIn("src/app.py", proc.stdout)

    def test_symbol_conflicts_use_dotted_prefixes(self):
        self.ok("reserve", "--agent", "qoder", "--symbols", "Order.total")
        proc = self.fails(3, "reserve", "--agent", "copilot", "--symbols", "Order.total.compute")
        self.assertIn("symbol", proc.stdout)
        self.ok("reserve", "--agent", "copilot", "--symbols", "Invoice.tax")

    def test_zero_ttl_reservation_does_not_block(self):
        self.ok("reserve", "--agent", "qoder", "--files", "src/app.py", "--ttl-minutes", "0")
        self.ok("reserve", "--agent", "copilot", "--files", "src/app.py")

    def test_same_agent_reservation_is_extended(self):
        first = self.ok("reserve", "--agent", "qoder", "--files", "src/app.py")
        second = self.ok("reserve", "--agent", "qoder", "--files", "src/app.py")
        self.assertIn("granted", first.stdout)
        self.assertIn("extended", second.stdout)

    def test_only_the_owner_releases_or_renews(self):
        self.ok("reserve", "--agent", "qoder", "--files", "src/app.py")
        proc = self.fails(2, "release", "--agent", "copilot", "--reservation", "R-0001")
        self.assertEqual(self.error_code(proc), "NOT_RESERVATION_OWNER")
        self.ok("renew", "--agent", "qoder", "--reservation", "R-0001", "--ttl-minutes", "5")
        self.ok("release", "--agent", "qoder", "--reservation", "R-0001")
        self.ok("reserve", "--agent", "copilot", "--files", "src/app.py")

    def test_empty_reservation_is_rejected(self):
        proc = self.fails(2, "reserve", "--agent", "qoder")
        self.assertEqual(self.error_code(proc), "EMPTY_RESERVATION")


class TestGate(BoardTestCase):
    def setUp(self):
        super().setUp()
        self.both_agents()
        self.ok(
            "plan", "propose", "--agent", "qoder", "--title", "Task 3", "--summary", "x",
            "--scope", "src",
        )

    def test_gate_needs_ack_then_reservation(self):
        proc = self.fails(
            3, "--json", "gate", "--agent", "qoder", "--plan", "P-0001", "--files", "src/app.py"
        )
        codes = self.gate_codes(proc)
        self.assertIn("PLAN_NOT_ACKED", codes)
        self.assertIn("NOT_RESERVED", codes)

        self.ok("plan", "ack", "--agent", "copilot", "--plan", "P-0001")
        proc = self.fails(
            3, "--json", "gate", "--agent", "qoder", "--plan", "P-0001", "--files", "src/app.py"
        )
        codes = self.gate_codes(proc)
        self.assertNotIn("PLAN_NOT_ACKED", codes)
        self.assertIn("NOT_RESERVED", codes)

        self.ok("reserve", "--agent", "qoder", "--plan", "P-0001", "--files", "src/app.py")
        allowed = self.ok(
            "--json", "gate", "--agent", "qoder", "--plan", "P-0001", "--files", "src/app.py"
        )
        self.assertEqual(json.loads(allowed.stdout)["decision"], "allow")

    def test_gate_reports_peer_owned_path(self):
        self.ok("plan", "ack", "--agent", "copilot", "--plan", "P-0001")
        self.ok("reserve", "--agent", "copilot", "--files", "src/")
        proc = self.fails(
            3, "--json", "gate", "--agent", "qoder", "--plan", "P-0001", "--files", "src/app.py"
        )
        self.assertIn("RESERVED_BY_PEER", self.gate_codes(proc))

    def test_gate_reports_expired_reservation(self):
        self.ok("plan", "ack", "--agent", "copilot", "--plan", "P-0001")
        self.ok("reserve", "--agent", "qoder", "--files", "src/app.py", "--ttl-minutes", "0")
        proc = self.fails(
            3, "--json", "gate", "--agent", "qoder", "--plan", "P-0001", "--files", "src/app.py"
        )
        self.assertIn("RESERVATION_EXPIRED", self.gate_codes(proc))

    def test_gate_blocks_unregistered_agent(self):
        proc = self.fails(3, "--json", "gate", "--agent", "stranger", "--files", "src/app.py")
        self.assertIn("AGENT_NOT_REGISTERED", self.gate_codes(proc))


class TestGateSolo(BoardTestCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.register("qoder", QODER_WT)
        self.ok(
            "plan", "propose", "--agent", "qoder", "--title", "bootstrap", "--summary", "x",
            "--scope", "a.py",
        )

    def test_solo_exemption_still_requires_a_reservation(self):
        proc = self.fails(
            3, "--json", "gate", "--agent", "qoder", "--plan", "P-0001", "--files", "a.py", "--allow-solo"
        )
        codes = self.gate_codes(proc)
        self.assertNotIn("PLAN_NOT_ACKED", codes)
        self.assertIn("NOT_RESERVED", codes)
        self.ok("reserve", "--agent", "qoder", "--plan", "P-0001", "--files", "a.py")
        self.ok("--json", "gate", "--agent", "qoder", "--plan", "P-0001", "--files", "a.py", "--allow-solo")

    def test_peer_registration_disables_the_solo_exemption(self):
        self.register("copilot", COPILOT_WT)
        self.ok("reserve", "--agent", "qoder", "--plan", "P-0001", "--files", "a.py")
        proc = self.fails(
            3, "--json", "gate", "--agent", "qoder", "--plan", "P-0001", "--files", "a.py", "--allow-solo"
        )
        self.assertIn("PLAN_NOT_ACKED", self.gate_codes(proc))


class TestMessages(BoardTestCase):
    def setUp(self):
        super().setUp()
        self.both_agents()

    def test_inbox_requires_ack_then_ack_clears_it(self):
        self.ok(
            "msg", "send", "--from", "qoder", "--to", "copilot",
            "--subject", "board is live", "--body", "read the board first",
        )
        inbox = json.loads(self.ok("--json", "msg", "inbox", "--agent", "copilot").stdout)
        self.assertEqual(inbox["count"], 1)
        self.assertEqual(inbox["messages"][0]["message_id"], "M-0001")
        self.assertEqual(
            json.loads(self.ok("--json", "msg", "inbox", "--agent", "qoder").stdout)["count"], 0
        )
        self.ok("msg", "ack", "--agent", "copilot", "--message", "M-0001")
        self.assertEqual(
            json.loads(self.ok("--json", "msg", "inbox", "--agent", "copilot").stdout)["count"], 0
        )
        self.assertEqual(
            json.loads(
                self.ok("--json", "msg", "inbox", "--agent", "copilot", "--all").stdout
            )["count"],
            1,
        )

    def test_non_recipient_cannot_ack(self):
        self.ok("msg", "send", "--from", "qoder", "--to", "copilot", "--subject", "s", "--body", "b")
        proc = self.fails(2, "msg", "ack", "--agent", "qoder", "--message", "M-0001")
        self.assertEqual(self.error_code(proc), "NOT_A_RECIPIENT")

    def test_empty_body_is_rejected(self):
        proc = self.fails(2, "msg", "send", "--from", "qoder", "--to", "copilot", "--subject", "s")
        self.assertEqual(self.error_code(proc), "EMPTY_MESSAGE")

    def test_broadcast_reaches_every_other_agent(self):
        self.register("auditor", "C:/tmp/auditor-wt")
        self.ok("msg", "send", "--from", "qoder", "--to", "all", "--subject", "broadcast", "--body", "noticed")
        for agent in ("copilot", "auditor"):
            payload = json.loads(self.ok("--json", "msg", "inbox", "--agent", agent).stdout)
            self.assertEqual(payload["count"], 1)


class TestProgressAndHandoff(BoardTestCase):
    def setUp(self):
        super().setUp()
        self.both_agents()
        self.ok(
            "plan", "propose", "--agent", "qoder", "--title", "Task 3", "--summary", "x",
            "--task-json", json.dumps({"id": "T1", "owner": "qoder", "title": "infra"}),
        )

    def test_status_set_updates_agent_and_task(self):
        self.ok("status", "set", "--agent", "qoder", "--state", "in_progress", "--task-id", "T1", "--note", "editing")
        snapshot = self.board_json()
        self.assertEqual(snapshot["agent_status"]["qoder"]["state"], "in_progress")
        self.assertEqual(snapshot["agent_status"]["qoder"]["task_id"], "T1")
        self.assertEqual(snapshot["plans"]["P-0001"]["tasks"][0]["status"], "in_progress")

    def test_invalid_state_is_rejected(self):
        proc = self.fails(2, "status", "set", "--agent", "qoder", "--state", "flying")
        self.assertEqual(self.error_code(proc), "INVALID_STATE")

    def test_handoff_marks_task_handed_off(self):
        self.ok(
            "handoff", "--agent", "qoder", "--task-id", "T1", "--plan", "P-0001",
            "--summary", "coordination infra delivered", "--files", ".agent-coordination/coord.py",
            "--tests", "unittest discover OK", "--next-steps", "copilot registers",
        )
        snapshot = self.board_json()
        self.assertEqual(snapshot["plans"]["P-0001"]["tasks"][0]["status"], "handed_off")
        self.assertEqual(snapshot["handoffs"]["H-0001"]["task_id"], "T1")
        self.assertEqual(snapshot["handoffs"]["H-0001"]["state"], "delivered")


class TestIntegrity(BoardTestCase):
    def setUp(self):
        super().setUp()
        self.both_agents()

    def events_path(self):
        return os.path.join(self.root, "events.jsonl")

    def rewrite_events(self, lines):
        with open(self.events_path(), "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(lines) + "\n")

    def test_edited_record_breaks_the_hash_chain(self):
        lines = [json.dumps(event, sort_keys=True, separators=(",", ":")) for event in self.events()]
        lines[1] = lines[1].replace('"display_name":"qoder"', '"display_name":"mallory"')
        self.rewrite_events(lines)
        proc = self.fails(4, "verify")
        self.assertIn("HASH_MISMATCH", proc.stdout)

    def test_truncated_tail_is_detected_by_the_anchor(self):
        lines = [json.dumps(event, sort_keys=True, separators=(",", ":")) for event in self.events()]
        self.rewrite_events(lines[:-1])
        proc = self.fails(4, "verify")
        self.assertIn("TAIL_TRUNCATED", proc.stdout)

    def test_anchor_behind_is_a_warning_not_a_failure(self):
        events = self.events()
        previous = events[-2]
        with open(os.path.join(self.root, "board", "HEAD.json"), "w", encoding="utf-8") as handle:
            json.dump(
                {"seq": previous["seq"], "hash": previous["hash"], "updated_at": previous["ts"]},
                handle,
            )
        payload = json.loads(self.ok("--json", "verify").stdout)
        self.assertTrue(payload["ok"])
        self.assertIn("HEAD_ANCHOR_BEHIND", {item["code"] for item in payload["problems"]})

    def test_board_snapshot_is_regenerated(self):
        before = os.path.getmtime(os.path.join(self.root, "board", "BOARD.md"))
        self.ok("board", "--write")
        self.assertGreaterEqual(os.path.getmtime(os.path.join(self.root, "board", "BOARD.md")), before)
        with open(os.path.join(self.root, "board", "BOARD.md"), encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("Qudron Coordination Board", content)
        self.assertIn("`qoder`", content)
        self.assertIn("`copilot`", content)


class TestConcurrentWrites(BoardTestCase):
    def setUp(self):
        super().setUp()
        self.both_agents()

    def test_parallel_appends_keep_one_contiguous_chain(self):
        workers = 8
        processes = [
            subprocess.Popen(
                [
                    sys.executable,
                    COORD,
                    "--root",
                    self.root,
                    "msg",
                    "send",
                    "--from",
                    "qoder",
                    "--to",
                    "copilot",
                    "--subject",
                    "concurrent-%02d" % index,
                    "--body",
                    "payload",
                    "--no-ack",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=self.root,
            )
            for index in range(workers)
        ]
        outputs = [process.communicate(timeout=180) for process in processes]
        for index, (stdout, stderr) in enumerate(outputs):
            self.assertEqual(
                processes[index].returncode,
                0,
                "worker %d failed\nstdout:\n%s\nstderr:\n%s" % (index, stdout, stderr),
            )

        verification = json.loads(self.ok("--json", "verify").stdout)
        self.assertTrue(verification["ok"], verification["problems"])

        events = self.events()
        self.assertEqual([event["seq"] for event in events], list(range(1, len(events) + 1)))
        sent = [event for event in events if event["type"] == "message.sent"]
        self.assertEqual(len(sent), workers)
        self.assertEqual(len({event["payload"]["message_id"] for event in sent}), workers)


class TestGateHardening(BoardTestCase):
    """Regression tests for the four blockers reported in message M-0002."""

    def setUp(self):
        super().setUp()
        self.both_agents()

    def propose(self, *extra):
        return self.ok(
            "plan", "propose", "--agent", "qoder", "--title", "hardening", "--summary", "x", *extra
        )

    def test_gate_requires_an_explicit_plan(self):
        proc = self.fails(3, "--json", "gate", "--agent", "qoder", "--files", "src/app.py")
        self.assertIn("PLAN_REQUIRED", self.gate_codes(proc))

    def test_gate_rejects_path_outside_plan_scope(self):
        self.propose("--scope", "src")
        self.ok("plan", "ack", "--agent", "copilot", "--plan", "P-0001")
        self.ok("reserve", "--agent", "qoder", "--files", "ops/tool.py")
        proc = self.fails(
            3, "--json", "gate", "--agent", "qoder", "--plan", "P-0001", "--files", "ops/tool.py"
        )
        self.assertIn("PLAN_SCOPE_MISMATCH", self.gate_codes(proc))

    def test_gate_rejects_plan_without_declared_scope(self):
        self.propose()
        self.ok("plan", "ack", "--agent", "copilot", "--plan", "P-0001")
        self.ok("reserve", "--agent", "qoder", "--files", "src/app.py")
        proc = self.fails(
            3, "--json", "gate", "--agent", "qoder", "--plan", "P-0001", "--files", "src/app.py"
        )
        self.assertIn("PLAN_SCOPE_UNDECLARED", self.gate_codes(proc))

    def test_symbol_edits_need_their_own_reservation(self):
        self.propose("--scope", "src", "--symbols", "Order.total")
        self.ok("plan", "ack", "--agent", "copilot", "--plan", "P-0001")
        self.ok("reserve", "--agent", "qoder", "--files", "src/app.py")
        proc = self.fails(
            3, "--json", "gate", "--agent", "qoder", "--plan", "P-0001",
            "--files", "src/app.py", "--symbols", "Order.total",
        )
        self.assertIn("NOT_RESERVED", self.gate_codes(proc))
        self.ok("reserve", "--agent", "qoder", "--symbols", "Order.total")
        allowed = self.ok(
            "--json", "gate", "--agent", "qoder", "--plan", "P-0001",
            "--files", "src/app.py", "--symbols", "Order.total",
        )
        self.assertEqual(json.loads(allowed.stdout)["decision"], "allow")

    def test_symbol_outside_plan_scope_is_blocked(self):
        self.propose("--scope", "src", "--symbols", "Invoice.tax")
        self.ok("plan", "ack", "--agent", "copilot", "--plan", "P-0001")
        self.ok("reserve", "--agent", "qoder", "--files", "src/app.py", "--symbols", "Order.total")
        proc = self.fails(
            3, "--json", "gate", "--agent", "qoder", "--plan", "P-0001",
            "--files", "src/app.py", "--symbols", "Order.total",
        )
        self.assertIn("PLAN_SCOPE_MISMATCH", self.gate_codes(proc))

    def test_plan_without_symbols_warns_but_still_requires_reservation(self):
        self.propose("--scope", "src")
        self.ok("plan", "ack", "--agent", "copilot", "--plan", "P-0001")
        proc = self.fails(
            3, "--json", "gate", "--agent", "qoder", "--plan", "P-0001", "--symbols", "Order.total"
        )
        payload = json.loads(proc.stdout)
        codes = {item["code"] for item in payload["reasons"]}
        self.assertIn("PLAN_SYMBOLS_UNDECLARED", codes)
        self.assertIn("NOT_RESERVED", codes)
        warnings = [
            item["code"] for item in payload["reasons"] if item.get("severity") == "warning"
        ]
        self.assertIn("PLAN_SYMBOLS_UNDECLARED", warnings)
        self.ok("reserve", "--agent", "qoder", "--symbols", "Order.total")
        self.ok("--json", "gate", "--agent", "qoder", "--plan", "P-0001", "--symbols", "Order.total")

    def test_peer_held_symbol_is_blocked(self):
        self.propose("--scope", "src", "--symbols", "Order.total")
        self.ok("plan", "ack", "--agent", "copilot", "--plan", "P-0001")
        self.ok("reserve", "--agent", "copilot", "--symbols", "Order.total")
        proc = self.fails(
            3, "--json", "gate", "--agent", "qoder", "--plan", "P-0001", "--symbols", "Order.total"
        )
        self.assertIn("RESERVED_BY_PEER", self.gate_codes(proc))


class TestPathCanonicalisation(BoardTestCase):
    def setUp(self):
        super().setUp()
        self.both_agents()

    def test_dotdot_alias_cannot_bypass_a_reservation(self):
        self.ok("reserve", "--agent", "qoder", "--files", "src/../file.py")
        proc = self.fails(3, "reserve", "--agent", "copilot", "--files", "file.py")
        self.assertIn("file.py", proc.stdout)

    def test_escaping_path_is_rejected(self):
        proc = self.fails(2, "reserve", "--agent", "qoder", "--files", "../outside.py")
        self.assertEqual(self.error_code(proc), "PATH_ESCAPES_ROOT")

    def test_absolute_path_needs_repo_root(self):
        proc = self.fails(2, "reserve", "--agent", "qoder", "--files", "C:/tmp/x.py")
        self.assertEqual(self.error_code(proc), "PATH_REQUIRES_REPO_ROOT")

    def test_absolute_path_is_relativised_against_repo_root(self):
        self.ok(
            "reserve", "--agent", "qoder", "--repo-root", self.root,
            "--files", os.path.join(self.root, "src", "app.py"),
        )
        proc = self.fails(3, "reserve", "--agent", "copilot", "--files", "src/app.py")
        self.assertIn("qoder", proc.stdout)

    def test_absolute_path_outside_repo_root_is_rejected(self):
        proc = self.fails(
            2, "reserve", "--agent", "qoder", "--repo-root", self.root, "--files", "C:/tmp/x.py"
        )
        self.assertEqual(self.error_code(proc), "PATH_OUTSIDE_REPO")


class TestVerifyHeadSnapshot(BoardTestCase):
    def setUp(self):
        super().setUp()
        self.both_agents()

    def load_module(self):
        spec = importlib.util.spec_from_file_location("coord_under_test", COORD)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_verify_head_uses_the_captured_snapshot(self):
        module = self.load_module()
        board = module.Board(self.root)
        events = board.read_events()
        # The verdict must be driven by the captured head, never by a fresh read
        # that may already contain another agent's append.
        stale = {"seq": len(events), "hash": "sha256:" + "f" * 64}
        codes = {item["code"] for item in module.verify_head(events, stale)}
        self.assertIn("ANCHOR_MISMATCH", codes)

        ahead = {"seq": len(events) + 3, "hash": events[-1]["hash"]}
        codes = {item["code"] for item in module.verify_head(events, ahead)}
        self.assertIn("TAIL_TRUNCATED", codes)

        current = {"seq": len(events), "hash": events[-1]["hash"]}
        self.assertEqual(module.verify_head(events, current), [])


class CraftedBoardMixin:
    """Inject an event the CLI would refuse, while keeping the board verifiable.

    ``Transaction`` keeps the hash chain and the anchor consistent, so the only
    rule bypassed is the business rule under test (for example an overlap that a
    command line check would have denied).
    """

    def load_module(self):
        spec = importlib.util.spec_from_file_location("coord_crafted", COORD)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def append_raw(self, event_type, agent, payload):
        module = self.load_module()
        with module.Board(self.root).transaction() as tx:
            return tx.append(event_type, agent, payload)

    def future_iso(self, minutes=30):
        module = self.load_module()
        return module.to_iso(module.utc_now() + module.timedelta(minutes=minutes))

    def crafted_lease(self, reservation_id, agent, paths=(), symbols=()):
        return self.append_raw(
            "reservation.granted",
            agent,
            {
                "reservation_id": reservation_id,
                "agent": agent,
                "plan_id": "P-0001",
                "paths": list(paths),
                "symbols": list(symbols),
                "ttl_minutes": 240,
                "expires_at": self.future_iso(),
                "note": "crafted overlapping lease",
            },
        )


class TestLeaseOverlap(CraftedBoardMixin, BoardTestCase):
    """Finding 1: lapsed leases are dead and live peer overlap always blocks.

    Before the fix a lease could be revived through ``renew`` without any
    conflict check, and the gate stopped looking at peer leases as soon as the
    caller held a covering reservation of its own.
    """

    def setUp(self):
        super().setUp()
        self.both_agents()
        self.ok(
            "plan", "propose", "--agent", "qoder", "--title", "overlap", "--summary", "x",
            "--scope", "src", "--symbols", "Order",
        )
        self.ok("plan", "ack", "--agent", "copilot", "--plan", "P-0001")

    def gate(self, *extra):
        return self.fails(
            3, "--json", "gate", "--agent", "qoder", "--plan", "P-0001", *extra
        )

    def test_expired_lease_cannot_be_renewed(self):
        self.ok("reserve", "--agent", "qoder", "--files", "src/app.py", "--ttl-minutes", "0")
        proc = self.fails(3, "renew", "--agent", "qoder", "--reservation", "R-0001")
        self.assertEqual(self.error_code(proc), "RESERVATION_EXPIRED")
        self.assertEqual(self.board_json()["reservations"]["R-0001"]["renewals"], 0)

    def test_reacquisition_after_expiry_runs_the_conflict_check(self):
        self.ok("reserve", "--agent", "qoder", "--files", "src/app.py", "--ttl-minutes", "0")
        self.ok("reserve", "--agent", "copilot", "--files", "src/app.py")
        proc = self.fails(3, "reserve", "--agent", "qoder", "--files", "src/app.py")
        self.assertIn("DENIED", proc.stdout)
        self.assertIn("RESERVED_BY_PEER", self.gate_codes(self.gate("--files", "src/app.py")))

    def test_gate_blocks_a_live_peer_overlap_even_with_our_own_covering_lease(self):
        self.ok("reserve", "--agent", "qoder", "--files", "src")
        self.crafted_lease("R-9101", "copilot", paths=["src/app.py"])
        proc = self.gate("--files", "src/app.py")
        codes = self.gate_codes(proc)
        self.assertIn("RESERVED_BY_PEER", codes)
        self.assertNotIn("NOT_RESERVED", codes)
        self.assertEqual(json.loads(proc.stdout)["decision"], "block")

    def test_gate_blocks_a_live_peer_symbol_overlap_even_with_our_own_symbol_lease(self):
        self.ok("reserve", "--agent", "qoder", "--symbols", "Order")
        self.crafted_lease("R-9102", "copilot", symbols=["Order.total"])
        proc = self.gate("--symbols", "Order")
        codes = self.gate_codes(proc)
        self.assertIn("RESERVED_BY_PEER", codes)
        self.assertNotIn("NOT_RESERVED", codes)

    def test_our_own_lease_alone_still_opens_the_gate(self):
        self.ok("reserve", "--agent", "qoder", "--files", "src")
        allowed = self.ok(
            "--json", "gate", "--agent", "qoder", "--plan", "P-0001", "--files", "src/app.py"
        )
        self.assertEqual(json.loads(allowed.stdout)["decision"], "allow")


class TestDirectionalAuthorization(CraftedBoardMixin, BoardTestCase):
    """Finding 2: symmetric overlap and directional containment are separate.

    Permission flows down (``src`` authorises ``src/app.py``), never up, while a
    peer lease overlaps in both directions because it answers a different
    question: who else could be editing this area right now.
    """

    def setUp(self):
        super().setUp()
        self.both_agents()
        self.ok(
            "plan", "propose", "--agent", "qoder", "--title", "directional", "--summary", "x",
            "--scope", "src", "--symbols", "Order",
        )
        self.ok("plan", "ack", "--agent", "copilot", "--plan", "P-0001")

    def gate(self, *extra):
        return self.fails(
            3, "--json", "gate", "--agent", "qoder", "--plan", "P-0001", *extra
        )

    def test_a_narrow_lease_does_not_authorise_the_parent_directory(self):
        self.ok("reserve", "--agent", "qoder", "--files", "src/app.py")
        self.assertIn("NOT_RESERVED", self.gate_codes(self.gate("--files", "src")))

    def test_a_directory_lease_authorises_its_children(self):
        self.ok("reserve", "--agent", "qoder", "--files", "src")
        allowed = self.ok(
            "--json", "gate", "--agent", "qoder", "--plan", "P-0001", "--files", "src/app.py"
        )
        self.assertEqual(json.loads(allowed.stdout)["decision"], "allow")

    def test_a_narrow_symbol_lease_does_not_authorise_the_parent_symbol(self):
        self.ok("reserve", "--agent", "qoder", "--symbols", "Order.total")
        self.assertIn("NOT_RESERVED", self.gate_codes(self.gate("--symbols", "Order")))

    def test_a_parent_symbol_lease_authorises_its_children(self):
        self.ok("reserve", "--agent", "qoder", "--symbols", "Order")
        allowed = self.ok(
            "--json", "gate", "--agent", "qoder", "--plan", "P-0001", "--symbols", "Order.total"
        )
        self.assertEqual(json.loads(allowed.stdout)["decision"], "allow")

    def test_a_peer_narrow_lease_blocks_the_parent_request_symmetrically(self):
        self.ok("reserve", "--agent", "copilot", "--files", "src/app.py")
        self.assertIn("RESERVED_BY_PEER", self.gate_codes(self.gate("--files", "src")))

    def test_a_peer_narrow_symbol_lease_blocks_the_parent_symbol(self):
        self.ok("reserve", "--agent", "copilot", "--symbols", "Order.total")
        self.assertIn("RESERVED_BY_PEER", self.gate_codes(self.gate("--symbols", "Order")))


class TestAckDiscipline(CraftedBoardMixin, BoardTestCase):
    """Finding 3: no ALLOW without a peer and a real, recognised ACK."""

    def solo_board(self):
        self.init()
        self.register("qoder", QODER_WT)
        self.ok(
            "plan", "propose", "--agent", "qoder", "--title", "bootstrap", "--summary", "x",
            "--scope", "a.py",
        )
        self.ok("reserve", "--agent", "qoder", "--plan", "P-0001", "--files", "a.py")

    def test_no_peer_and_no_ack_blocks(self):
        self.solo_board()
        proc = self.fails(
            3, "--json", "gate", "--agent", "qoder", "--plan", "P-0001", "--files", "a.py"
        )
        self.assertIn("PEER_REQUIRED", self.gate_codes(proc))

    def test_bootstrap_exemption_is_explicit(self):
        self.solo_board()
        allowed = self.ok(
            "--json", "gate", "--agent", "qoder", "--plan", "P-0001", "--files", "a.py",
            "--allow-solo",
        )
        payload = json.loads(allowed.stdout)
        self.assertEqual(payload["decision"], "allow")
        codes = {item["code"] for item in payload["reasons"]}
        self.assertIn("SOLO_BOOTSTRAP_EXEMPTION", codes)
        warnings = [
            item["code"] for item in payload["reasons"] if item.get("severity") == "warning"
        ]
        self.assertIn("SOLO_BOOTSTRAP_EXEMPTION", warnings)

    def test_bootstrap_exemption_is_time_bounded(self):
        self.solo_board()
        proc = self.fails(
            3, "--json", "gate", "--agent", "qoder", "--plan", "P-0001", "--files", "a.py",
            "--allow-solo", "--bootstrap-window-minutes", "0",
        )
        self.assertIn("BOOTSTRAP_EXEMPTION_DENIED", self.gate_codes(proc))

    def test_an_ack_from_an_unknown_identity_does_not_count(self):
        self.both_agents()
        self.ok(
            "plan", "propose", "--agent", "qoder", "--title", "forged", "--summary", "x",
            "--scope", "src",
        )
        self.ok("reserve", "--agent", "qoder", "--files", "src/app.py")
        self.append_raw("plan.acknowledged", "mallory", {"plan_id": "P-0001", "note": "forged"})
        proc = self.fails(
            3, "--json", "gate", "--agent", "qoder", "--plan", "P-0001", "--files", "src/app.py"
        )
        self.assertIn("PLAN_NOT_ACKED", self.gate_codes(proc))
        self.ok("plan", "ack", "--agent", "copilot", "--plan", "P-0001")
        allowed = self.ok(
            "--json", "gate", "--agent", "qoder", "--plan", "P-0001", "--files", "src/app.py"
        )
        self.assertEqual(json.loads(allowed.stdout)["decision"], "allow")


class TestIntegrityUnderLock(BoardTestCase):
    """Finding 4: chain and anchor are checked under the lock before any write."""

    def setUp(self):
        super().setUp()
        self.both_agents()
        self.ok(
            "plan", "propose", "--agent", "qoder", "--title", "guard", "--summary", "x",
            "--scope", "src",
        )
        self.ok("plan", "ack", "--agent", "copilot", "--plan", "P-0001")

    def events_path(self):
        return os.path.join(self.root, "events.jsonl")

    def head_path(self):
        return os.path.join(self.root, "board", "HEAD.json")

    def head_text(self):
        with open(self.head_path(), "r", encoding="utf-8") as handle:
            return handle.read()

    def log_text(self):
        with open(self.events_path(), "r", encoding="utf-8") as handle:
            return handle.read()

    def corrupt_chain(self):
        events = self.events()
        events[1]["payload"]["display_name"] = "mallory"
        with open(self.events_path(), "w", encoding="utf-8", newline="\n") as handle:
            handle.write(
                "\n".join(
                    json.dumps(event, sort_keys=True, separators=(",", ":")) for event in events
                )
                + "\n"
            )

    def truncate_log(self):
        lines = [line for line in self.log_text().splitlines() if line.strip()]
        with open(self.events_path(), "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(lines[:-1]) + "\n")

    def test_mutation_is_refused_and_the_anchor_is_not_rewritten(self):
        head_before = self.head_text()
        self.corrupt_chain()
        corrupted_log = self.log_text()
        proc = self.fails(
            4, "msg", "send", "--from", "qoder", "--to", "copilot", "--subject", "s",
            "--body", "b",
        )
        self.assertEqual(self.error_code(proc), "BOARD_CORRUPT")
        self.assertEqual(self.head_text(), head_before)
        self.assertEqual(self.log_text(), corrupted_log)

    def test_gate_is_refused_on_a_corrupt_log(self):
        self.corrupt_chain()
        proc = self.fails(
            4, "--json", "gate", "--agent", "qoder", "--plan", "P-0001", "--files", "src/app.py"
        )
        self.assertEqual(self.error_code(proc), "BOARD_CORRUPT")

    def test_a_truncated_log_blocks_a_reservation_and_keeps_the_anchor(self):
        head_before = self.head_text()
        self.truncate_log()
        proc = self.fails(4, "reserve", "--agent", "qoder", "--files", "src/app.py")
        self.assertEqual(self.error_code(proc), "BOARD_CORRUPT")
        self.assertEqual(self.head_text(), head_before)


class TestVerifyStates(BoardTestCase):
    """Finding 5: uninitialized, ok and corrupt are three different answers."""

    def events_path(self):
        return os.path.join(self.root, "events.jsonl")

    def head_path(self):
        return os.path.join(self.root, "board", "HEAD.json")

    def test_an_uninitialized_board_is_named_as_such(self):
        payload = json.loads(self.ok("--json", "verify").stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"], "uninitialized")
        self.assertEqual(payload["events"], 0)
        self.assertIn("UNINITIALIZED", self.ok("verify").stdout)

    def test_a_missing_log_under_an_anchor_is_corruption(self):
        self.init()
        os.remove(self.events_path())
        proc = self.fails(4, "verify")
        self.assertIn("LOG_MISSING", proc.stdout)
        self.assertFalse(json.loads(self.fails(4, "--json", "verify").stdout)["ok"])

    def test_an_empty_log_under_an_anchor_is_corruption(self):
        self.init()
        with open(self.events_path(), "w", encoding="utf-8"):
            pass
        self.assertIn("LOG_MISSING", self.fails(4, "verify").stdout)
        self.assertEqual(
            json.loads(self.fails(4, "--json", "verify").stdout)["status"], "corrupt"
        )

    def test_an_unparsable_anchor_is_corruption(self):
        self.init()
        with open(self.head_path(), "w", encoding="utf-8") as handle:
            handle.write("{not json")
        self.assertIn("HEAD_ANCHOR_INVALID", self.fails(4, "verify").stdout)

    def test_a_healthy_board_reports_ok(self):
        self.init()
        payload = json.loads(self.ok("--json", "verify").stdout)
        self.assertEqual(payload["status"], "ok")


class TestWindowsPathForms(BoardTestCase):
    """Finding 6: spellings Windows would silently rewrite are rejected."""

    def setUp(self):
        super().setUp()
        self.both_agents()

    def test_plan_scope_with_a_trailing_dot_is_rejected(self):
        proc = self.fails(
            2, "plan", "propose", "--agent", "qoder", "--title", "t", "--scope", "src/app.py."
        )
        self.assertEqual(self.error_code(proc), "PATH_INVALID_COMPONENT")

    def test_plan_scope_with_a_trailing_space_component_is_rejected(self):
        proc = self.fails(
            2, "plan", "propose", "--agent", "qoder", "--title", "t", "--scope", "src /app.py"
        )
        self.assertEqual(self.error_code(proc), "PATH_INVALID_COMPONENT")

    def test_task_files_use_the_same_strict_normaliser(self):
        task = {"id": "T1", "owner": "qoder", "files": ["src/app.py."]}
        proc = self.fails(
            2, "plan", "propose", "--agent", "qoder", "--title", "t",
            "--task-json", json.dumps(task),
        )
        self.assertEqual(self.error_code(proc), "PATH_INVALID_COMPONENT")

    def test_reserve_rejects_an_alternate_data_stream(self):
        proc = self.fails(2, "reserve", "--agent", "qoder", "--files", "src/app.py:hidden")
        self.assertEqual(self.error_code(proc), "PATH_ADS_FORBIDDEN")

    def test_reserve_rejects_a_drive_relative_path(self):
        proc = self.fails(2, "reserve", "--agent", "qoder", "--files", "C:src/app.py")
        self.assertEqual(self.error_code(proc), "PATH_DRIVE_RELATIVE")

    def test_gate_rejects_the_same_spellings(self):
        self.ok(
            "plan", "propose", "--agent", "qoder", "--title", "paths", "--summary", "x",
            "--scope", "src",
        )
        self.ok("plan", "ack", "--agent", "copilot", "--plan", "P-0001")
        cases = (
            ("src/app.py.", "PATH_INVALID_COMPONENT"),
            ("src /app.py", "PATH_INVALID_COMPONENT"),
            ("src/app.py:hidden", "PATH_ADS_FORBIDDEN"),
            ("C:src/app.py", "PATH_DRIVE_RELATIVE"),
        )
        for raw, code in cases:
            proc = self.fails(
                2, "gate", "--agent", "qoder", "--plan", "P-0001", "--files", raw
            )
            self.assertEqual(self.error_code(proc), code, "raw=%r" % raw)


class TestTaskAddressing(BoardTestCase):
    """Finding 7: a task is addressed by plan_id together with task_id."""

    def setUp(self):
        super().setUp()
        self.both_agents()
        self.ok(
            "plan", "propose", "--agent", "qoder", "--title", "one", "--summary", "x",
            "--scope", "a.py",
            "--task-json", json.dumps({"id": "T1", "owner": "qoder", "title": "infra"}),
        )
        self.ok(
            "plan", "propose", "--agent", "copilot", "--title", "two", "--summary", "x",
            "--scope", "b.py",
            "--task-json", json.dumps({"id": "T1", "owner": "copilot", "title": "peer work"}),
        )

    def test_an_ambiguous_task_id_is_refused(self):
        proc = self.fails(
            2, "status", "set", "--agent", "qoder", "--state", "in_progress", "--task-id", "T1"
        )
        self.assertEqual(self.error_code(proc), "TASK_REFERENCE_AMBIGUOUS")

    def test_plan_and_task_id_select_exactly_one_task(self):
        self.ok(
            "status", "set", "--agent", "qoder", "--plan", "P-0001", "--state", "in_progress",
            "--task-id", "T1",
        )
        snapshot = self.board_json()
        self.assertEqual(snapshot["plans"]["P-0001"]["tasks"][0]["status"], "in_progress")
        self.assertEqual(snapshot["plans"]["P-0002"]["tasks"][0]["status"], "pending")
        self.assertEqual(self.events()[-1]["payload"]["plan_id"], "P-0001")

    def test_an_unknown_task_is_reported(self):
        proc = self.fails(
            2, "status", "set", "--agent", "qoder", "--plan", "P-0001", "--state", "in_progress",
            "--task-id", "T9",
        )
        self.assertEqual(self.error_code(proc), "TASK_NOT_FOUND")

    def test_a_peer_task_cannot_be_claimed(self):
        proc = self.fails(
            2, "status", "set", "--agent", "qoder", "--plan", "P-0002", "--state", "in_progress",
            "--task-id", "T1",
        )
        self.assertEqual(self.error_code(proc), "TASK_NOT_OWNED")

    def test_handoff_needs_the_plan_when_ids_collide(self):
        proc = self.fails(2, "handoff", "--agent", "qoder", "--task-id", "T1", "--summary", "done")
        self.assertEqual(self.error_code(proc), "TASK_REFERENCE_AMBIGUOUS")
        self.ok("handoff", "--agent", "qoder", "--plan", "P-0001", "--task-id", "T1", "--summary", "done")
        handoff = self.board_json()["handoffs"]["H-0001"]
        self.assertEqual(handoff["plan_id"], "P-0001")
        self.assertEqual(handoff["task_id"], "T1")

    def test_an_unknown_plan_is_reported(self):
        proc = self.fails(
            2, "handoff", "--agent", "qoder", "--plan", "P-9999", "--task-id", "T1",
            "--summary", "done",
        )
        self.assertEqual(self.error_code(proc), "PLAN_NOT_FOUND")


class TestDocumentation(unittest.TestCase):
    """Finding 8: one peer identity, and an outbound ACK check in the runbook."""

    def read(self, name):
        with open(os.path.join(BOARD_DIR, name), "r", encoding="utf-8") as handle:
            return handle.read()

    def test_readme_uses_the_registered_peer_identity(self):
        text = self.read("README.md")
        for stale in ("--agent copilot", "--from copilot", "--to copilot"):
            self.assertNotIn(stale, text, "README.md still instructs %r" % stale)
        self.assertIn("--agent github-copilot", text)

    def test_readme_explains_checking_an_outbound_ack_from_board_state(self):
        text = self.read("README.md")
        self.assertIn("acked_by", text)
        self.assertIn("--json board", text)

    def test_protocol_documents_the_new_refusals(self):
        text = self.read("PROTOCOL.md")
        for code in (
            "PEER_REQUIRED",
            "BOOTSTRAP_EXEMPTION_DENIED",
            "SOLO_BOOTSTRAP_EXEMPTION",
            "RESERVED_BY_PEER",
            "RESERVATION_EXPIRED",
            "LOG_MISSING",
            "BOARD_CORRUPT",
            "TASK_REFERENCE_AMBIGUOUS",
            "PATH_INVALID_COMPONENT",
            "PATH_ADS_FORBIDDEN",
            "PATH_DRIVE_RELATIVE",
        ):
            self.assertIn(code, text, "PROTOCOL.md does not document %s" % code)


if __name__ == "__main__":
    unittest.main(verbosity=2)
