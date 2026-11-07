import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import agent_fleet


class WorkerBindingValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="qudron-binding-")
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        agent_fleet.git(["init"], self.repo)
        agent_fleet.git(["config", "user.name", "Qudron CI"], self.repo)
        agent_fleet.git(["config", "user.email", "qudron-ci@example.invalid"], self.repo)
        (self.repo / "README.md").write_text("base\n", encoding="utf-8")
        agent_fleet.git(["add", "README.md"], self.repo)
        agent_fleet.git(["commit", "-m", "base"], self.repo)
        self.base_sha = agent_fleet.git(["rev-parse", "HEAD"], self.repo).stdout.strip()
        self.worktree_root = self.root / "worktrees"
        self.worktree_root.mkdir()
        self.artifact_dir = self.root / "artifacts"
        self.artifact_dir.mkdir()
        self.branch = "agent-fleet/binding-test/task-one"
        self.worktree = self.worktree_root / "task-one"
        agent_fleet.git(
            ["worktree", "add", "-b", self.branch, str(self.worktree), self.base_sha],
            self.repo,
        )
        self.prepared = {
            "task": {
                "id": "task-one",
                "title": "Binding validation test",
                "agent": "codex",
                "mode": "implement",
                "prompt": "write one scoped file",
                "base_ref": self.base_sha,
                "allowed_paths": ["worker.txt"],
                "deny_paths": list(agent_fleet.DEFAULT_DENY_PATHS),
            },
            "base_sha": self.base_sha,
            "worktree": self.worktree,
            "branch": self.branch,
            "prompt": "write one scoped file",
            "prompt_file": self.artifact_dir / "task-one.prompt.md",
        }
        agent_fleet.safe_write(self.prepared["prompt_file"], "test prompt")

    def tearDown(self) -> None:
        agent_fleet.git(
            ["worktree", "remove", "--force", str(self.worktree)],
            self.repo,
            check=False,
        )
        shutil.rmtree(self.root, ignore_errors=True)
        self.temp.cleanup()

    def test_unchanged_worktree_branch_and_head_are_accepted(self) -> None:
        result = agent_fleet.verify_worker_binding(self.prepared)
        self.assertEqual(result["head_sha"], self.base_sha)
        self.assertEqual(result["violations"], [])

    def test_switching_branch_invalidates_worker_binding(self) -> None:
        agent_fleet.git(["checkout", "--detach"], self.worktree)
        result = agent_fleet.verify_worker_binding(self.prepared)
        self.assertIn("worker_branch_mismatch", result["violations"])
        self.assertEqual(result["head_sha"], self.base_sha)

    def test_worker_commit_blocks_patch_and_log_handoff(self) -> None:
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        cli = fake_bin / "codex"
        cli.write_text(
            "#!/usr/bin/env python3\n"
            "from pathlib import Path\n"
            "import subprocess\n"
            "Path('worker.txt').write_text('worker output\\n', encoding='utf-8')\n"
            "subprocess.run(['git', 'add', 'worker.txt'], check=True)\n"
            "subprocess.run(['git', '-c', 'user.name=Worker', '-c', "
            "'user.email=worker@example.invalid', 'commit', '-m', "
            "'unexpected worker commit'], check=True)\n"
            "print('{}')\n",
            encoding="utf-8",
        )
        cli.chmod(0o755)
        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = str(fake_bin) + os.pathsep + old_path
        try:
            result = agent_fleet.execute_task(
                self.prepared, self.artifact_dir, timeout=60, capture_logs=True
            )
        finally:
            os.environ["PATH"] = old_path
        self.assertEqual(result["status"], "scope_violation")
        self.assertNotEqual(result["head_sha"], self.base_sha)
        self.assertIn("worker_head_moved", result["binding_violations"])
        self.assertFalse(result["patch_exported"])
        self.assertFalse(result["logs_exported"])
        self.assertIsNone(result["patch_path"])
        self.assertIsNone(result["stdout_path"])
        self.assertIsNone(result["stderr_path"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
