"""
Unit tests for ops/qudron-runtime/local_agent_fleet.py
Focusing on:
1. HostSemaphore
2. TaskCapsule
3. DurableTaskQueue
4. ZeroTokenContextBus
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

# Ensure ops/qudron-runtime is on sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from local_agent_fleet import (
    AgentRole,
    DurableTaskQueue,
    FleetCoordinator,
    HostSemaphore,
    TaskCapsule,
    ZeroTokenContextBus,
)


class TestHostSemaphore(unittest.TestCase):
    def test_host_semaphore_blocks_concurrent_acquire(self):
        sem = HostSemaphore(max_concurrent=1, timeout_sec=2)
        acquired_first = threading.Event()
        acquired_second = threading.Event()
        second_blocked = threading.Event()

        def worker1():
            with sem.acquire("task-1"):
                acquired_first.set()
                # Hold until signal
                second_blocked.wait(timeout=2)

        def worker2():
            acquired_first.wait(timeout=2)
            # Try acquire - should block while worker1 holds
            with sem.acquire("task-2"):
                acquired_second.set()

        t1 = threading.Thread(target=worker1, daemon=True)
        t2 = threading.Thread(target=worker2, daemon=True)

        t1.start()
        acquired_first.wait(timeout=2)
        self.assertEqual(sem.active_tasks, ["task-1"])

        t2.start()
        # Give t2 a short moment to attempt acquire
        t2.join(timeout=0.1)
        self.assertFalse(acquired_second.is_set(), "Second worker should be blocked")

        # Unblock worker1
        second_blocked.set()
        t1.join(timeout=2)
        t2.join(timeout=2)
        self.assertTrue(acquired_second.is_set(), "Second worker should acquire after release")

    def test_host_semaphore_timeout_raises_error(self):
        # Set timeout_sec = -1 to trigger instant timeout when blocked
        sem = HostSemaphore(max_concurrent=1, timeout_sec=-1)
        with sem.acquire("task-held"):
            self.assertIn("task-held", sem.active_tasks)
            with self.assertRaises(TimeoutError):
                with sem.acquire("task-overflow"):
                    pass

    def test_host_semaphore_release_frees_slot(self):
        sem = HostSemaphore(max_concurrent=1, timeout_sec=1)
        self.assertEqual(len(sem.active_tasks), 0)

        with sem.acquire("job-a"):
            self.assertEqual(sem.active_tasks, ["job-a"])

        self.assertEqual(len(sem.active_tasks), 0)

        # Another acquire must succeed immediately
        with sem.acquire("job-b"):
            self.assertEqual(sem.active_tasks, ["job-b"])

        self.assertEqual(len(sem.active_tasks), 0)


class TestTaskCapsule(unittest.TestCase):
    def setUp(self):
        self.capsule = TaskCapsule(
            task_id="task-101",
            task_type="coding",
            owner=AgentRole.QODER,
            reviewer=AgentRole.COPILOT,
            target_files=["ops/qudron-runtime/qudron_worker.py", "ops/qudron-runtime/continuity_store.py"],
            target_symbols=["HostSemaphore", "ZeroTokenContextBus"],
            diff_summary="Add robust Windows SQLite retry logic and platform checks",
            learned_rules=["rule: always close sqlite3 before cleanup", "rule: guard chmod on nt"],
            priority=3,
        )

    def test_capsule_compact_json_length(self):
        compact = self.capsule.to_compact_json()
        self.assertIsInstance(compact, str)
        # Verify JSON is compact and well under 800 characters
        self.assertLess(len(compact), 800)
        parsed = json.loads(compact)
        self.assertEqual(parsed["id"], "task-101")
        self.assertEqual(parsed["owner"], "qoder")
        self.assertEqual(len(parsed["files"]), 2)
        self.assertEqual(len(parsed["symbols"]), 2)
        self.assertEqual(len(parsed["rules"]), 2)

    def test_capsule_token_estimate_positive(self):
        est = self.capsule.token_estimate()
        self.assertIsInstance(est, int)
        self.assertGreater(est, 0)
        # Should be well below 200 tokens
        self.assertLess(est, 200)


class TestDurableTaskQueue(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.temp_dir.name) / "test_queue.sqlite3"
        self.queue = DurableTaskQueue(db_path=self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _make_capsule(self, task_id="t-1", owner=AgentRole.QODER, priority=5):
        return TaskCapsule(
            task_id=task_id,
            task_type="coding",
            owner=owner,
            reviewer=AgentRole.COPILOT,
            target_files=["src/test.py"],
            target_symbols=["test_fn"],
            diff_summary="Implement test_fn",
            learned_rules=["rule-1"],
            priority=priority,
        )

    def test_enqueue_and_claim_next(self):
        capsule = self._make_capsule("task-claim-1", owner=AgentRole.QODER, priority=2)
        self.queue.enqueue(capsule)

        claimed = self.queue.claim_next(AgentRole.QODER)
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed["task_id"], "task-claim-1")
        self.assertEqual(claimed["owner"], "qoder")
        self.assertEqual(claimed["attempts"], 1)

    def test_claim_next_empty_returns_none(self):
        claimed = self.queue.claim_next(AgentRole.KIRO)
        self.assertIsNone(claimed)

    def test_complete_sets_done(self):
        capsule = self._make_capsule("task-complete-1", owner=AgentRole.ANTIGRAVITY)
        self.queue.enqueue(capsule)
        self.queue.claim_next(AgentRole.ANTIGRAVITY)

        self.queue.complete("task-complete-1", result_ref="sha256:abc123def")
        stats = self.queue.queue_stats()
        self.assertEqual(stats.get("done"), 1)

    def test_fail_below_max_attempts_returns_to_pending(self):
        capsule = self._make_capsule("task-retry-1", owner=AgentRole.QODER)
        self.queue.enqueue(capsule)

        # 1st attempt: claim & fail (max_attempts = 3)
        claimed = self.queue.claim_next(AgentRole.QODER)
        self.assertIsNotNone(claimed)
        self.queue.fail("task-retry-1", error_msg="transient network timeout")

        stats = self.queue.queue_stats()
        self.assertEqual(stats.get("pending"), 1)

        # Should be claimable again
        claimed_again = self.queue.claim_next(AgentRole.QODER)
        self.assertIsNotNone(claimed_again)
        self.assertEqual(claimed_again["attempts"], 2)

    def test_fail_at_max_attempts_sets_failed(self):
        capsule = self._make_capsule("task-fail-max", owner=AgentRole.QODER)
        self.queue.enqueue(capsule)

        # Exhaust 3 attempts
        for _ in range(3):
            self.queue.claim_next(AgentRole.QODER)
            self.queue.fail("task-fail-max", error_msg="persistent error")

        stats = self.queue.queue_stats()
        self.assertEqual(stats.get("failed"), 1)
        self.assertIsNone(self.queue.claim_next(AgentRole.QODER))


class TestZeroTokenContextBus(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.temp_dir.name) / "test_bus.sqlite3"
        self.bus = ZeroTokenContextBus(db_path=self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_record_stores_entry(self):
        self.bus.record(
            agent=AgentRole.ANTIGRAVITY,
            entry_type="capsule",
            content="Dispatched infra task for test suite hardening",
            task_id="t-record-1",
            tags=["infra", "test"],
        )
        entries = self.bus.fetch_relevant(task_id="t-record-1")
        self.assertEqual(len(entries), 1)
        self.assertIn("Dispatched infra task", entries[0])
        self.assertIn("antigravity:capsule", entries[0])

    def test_fetch_relevant_filters_by_task_id(self):
        self.bus.record(agent=AgentRole.QODER, entry_type="result", content="Result for task A", task_id="task-A")
        self.bus.record(agent=AgentRole.COPILOT, entry_type="review", content="Review for task B", task_id="task-B")
        self.bus.record(agent=AgentRole.KIRO, entry_type="capsule", content="Draft for task A", task_id="task-A")

        relevant_a = self.bus.fetch_relevant(task_id="task-A")
        self.assertEqual(len(relevant_a), 2)
        for entry in relevant_a:
            self.assertNotIn("task B", entry)

        relevant_b = self.bus.fetch_relevant(task_id="task-B")
        self.assertEqual(len(relevant_b), 1)
        self.assertIn("Review for task B", relevant_b[0])

    def test_fetch_learned_rules_returns_rules_only(self):
        self.bus.record(agent=AgentRole.ANTIGRAVITY, entry_type="rule", content="rule: use HostSemaphore max=1")
        self.bus.record(agent=AgentRole.COPILOT, entry_type="result", content="result: tests passed")
        self.bus.record(agent=AgentRole.KIRO, entry_type="rule", content="rule: single-writer per component")

        rules = self.bus.fetch_learned_rules(limit=10)
        self.assertEqual(len(rules), 2)
        self.assertIn("rule: use HostSemaphore max=1", rules)
        self.assertIn("rule: single-writer per component", rules)


class TestSuperAgentExecutors(unittest.TestCase):
    """Integration tests for the three super-agent capabilities."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self.temp_dir.name)
        self.fleet = FleetCoordinator()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_run_super_task_unknown_type(self):
        result = self.fleet.run_super_task("unknown_type")
        self.assertFalse(result.get("ok"))
        self.assertIn("Unknown super task type", result.get("error", ""))

    def test_run_super_task_meta_developer_missing_args(self):
        result = self.fleet.run_super_task("meta_developer")
        self.assertFalse(result.get("ok"))
        self.assertIn("required", result.get("error", ""))

    def test_run_super_task_meta_developer_no_api_call(self):
        result = self.fleet.run_super_task(
            "meta_developer",
            capability_name="System Info Tool",
            requirements="A tool to get CPU and RAM usage using psutil",
        )
        self.assertIn("ok", result)
        if result.get("ok"):
            self.assertIn("tool_path", result)
            self.assertIn("capability_id", result)
            self.assertTrue(result["capability_id"].startswith("meta:"))

    def test_run_super_task_computer_use_returns_structure(self):
        result = self.fleet.run_super_task(
            "computer_use",
            goal="Take a screenshot and analyze it",
            max_steps=1,
        )
        self.assertIn("ok", result)
        self.assertIn("steps_executed", result)
        self.assertIn("last_result", result)

    def test_run_super_task_multi_perspective_requires_capsule(self):
        result = self.fleet.run_super_task("multi_perspective")
        self.assertFalse(result.get("ok"))
        self.assertIn("capsule", result.get("error", "").lower())

    def test_run_super_task_multi_perspective_with_capsule(self):
        capsule = TaskCapsule(
            task_id="multi-test-1",
            task_type="review",
            owner=AgentRole.COPILOT,
            reviewer=None,
            target_files=["ops/qudron-runtime/local_agent_fleet.py"],
            target_symbols=["FleetCoordinator"],
            diff_summary="Review the FleetCoordinator class for security issues",
            learned_rules=[],
            priority=2,
        )
        result = self.fleet.run_super_task("multi_perspective", capsule=capsule, context=[])
        self.assertIn("ok", result)
        self.assertIn("perspectives", result)
        self.assertIn("summary", result)
        self.assertEqual(4, len(result["perspectives"]))


if __name__ == "__main__":
    unittest.main()
