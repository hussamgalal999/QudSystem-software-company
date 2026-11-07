import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.dev_worktree_orchestrator import (
    WorktreeError, collect, load_manifest, prepare, status,
)


class DevWorktreeOrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Qudron Test"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "qudron-test@example.invalid"], check=True)
        (self.repo / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
        (self.repo / "b.py").write_text("VALUE = 2\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.repo), "add", "a.py", "b.py"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "seed"], check=True)
        self.base = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], check=True, text=True, capture_output=True).stdout.strip()
        self.manifest = self.root / "tasks.json"
        self.worktrees = self.root / "workers"
        self.artifacts = self.root / "artifacts"

    def tearDown(self):
        if self.worktrees.exists():
            for path in self.worktrees.iterdir():
                if path.name == ".qudron-control":
                    continue
                if path.is_dir():
                    subprocess.run(["git", "-C", str(self.repo), "worktree", "remove", "--force", str(path)], check=False, capture_output=True)
            shutil = __import__("shutil")
            shutil.rmtree(self.worktrees, ignore_errors=True)
        self.temp.cleanup()

    def write_manifest(self, tasks=None):
        data = {
            "version": 1,
            "base_ref": "HEAD",
            "tasks": tasks or [{
                "task_id": "worker-alpha",
                "title": "Change a.py",
                "objective": "Update the first module.",
                "allowed_paths": ["a.py"],
                "acceptance_criteria": ["The module remains valid Python."],
            }],
        }
        self.manifest.write_text(json.dumps(data), encoding="utf-8")

    def test_rejects_path_traversal(self):
        self.write_manifest([{
            "task_id": "worker-alpha", "title": "Bad", "objective": "Bad path",
            "allowed_paths": ["../outside.py"], "acceptance_criteria": ["No traversal"],
        }])
        with self.assertRaises(WorktreeError):
            load_manifest(self.manifest)

    def test_rejects_overlapping_parallel_write_scopes(self):
        self.write_manifest([
            {"task_id": "worker-alpha", "title": "A", "objective": "A", "allowed_paths": ["src/**"], "acceptance_criteria": ["A"]},
            {"task_id": "worker-bravo", "title": "B", "objective": "B", "allowed_paths": ["src/module.py"], "acceptance_criteria": ["B"]},
        ])
        with self.assertRaisesRegex(WorktreeError, "Overlapping write scopes"):
            load_manifest(self.manifest)

    def test_prepare_creates_distinct_branches_and_worktrees(self):
        self.write_manifest([
            {"task_id": "worker-alpha", "title": "A", "objective": "A", "allowed_paths": ["a.py"], "acceptance_criteria": ["A"]},
            {"task_id": "worker-bravo", "title": "B", "objective": "B", "allowed_paths": ["b.py"], "acceptance_criteria": ["B"]},
        ])
        result = prepare(self.repo, self.manifest, self.worktrees)
        self.assertEqual(len(result["tasks"]), 2)
        self.assertNotEqual(result["tasks"][0]["branch"], result["tasks"][1]["branch"])
        self.assertTrue(Path(result["tasks"][0]["worktree"]).is_dir())
        self.assertEqual(len(status(self.worktrees)["tasks"]), 2)

    def test_collect_exports_patch_only_for_authorized_paths(self):
        self.write_manifest()
        prepare(self.repo, self.manifest, self.worktrees)
        worktree = self.worktrees / "worker-alpha"
        (worktree / "a.py").write_text("VALUE = 42\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(worktree), "add", "a.py"], check=True)
        control = worktree / ".qudron-worker"
        control.mkdir()
        result = {
            "schema_version": 1, "task_id": "worker-alpha", "status": "completed",
            "summary": "Updated the value with a targeted change.", "base_sha": self.base,
            "head_sha": self.base, "changed_files": ["a.py"],
            "tests": [{"name": "Python syntax", "status": "passed", "evidence": "test.log"}],
            "risks": [], "requires_human_review": True,
        }
        (control / "result.json").write_text(json.dumps(result), encoding="utf-8")
        (control / "test.log").write_text("python -m py_compile a.py\nPASS\n", encoding="utf-8")
        artifact = collect(self.worktrees, "worker-alpha", self.artifacts)
        self.assertEqual(artifact["changed_files"], ["a.py"])
        patch = Path(artifact["patch"]).read_text(encoding="utf-8")
        self.assertIn("VALUE = 42", patch)
        self.assertTrue((self.artifacts / "worker-alpha" / "test.log").is_file())

    def test_collect_rejects_changes_outside_scope(self):
        self.write_manifest()
        prepare(self.repo, self.manifest, self.worktrees)
        worktree = self.worktrees / "worker-alpha"
        (worktree / "b.py").write_text("VALUE = 99\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(worktree), "add", "b.py"], check=True)
        control = worktree / ".qudron-worker"
        control.mkdir()
        result = {
            "schema_version": 1, "task_id": "worker-alpha", "status": "completed",
            "summary": "Attempted an out-of-scope change.", "base_sha": self.base,
            "head_sha": self.base, "changed_files": ["b.py"], "tests": [],
            "risks": [], "requires_human_review": True,
        }
        (control / "result.json").write_text(json.dumps(result), encoding="utf-8")
        with self.assertRaisesRegex(WorktreeError, "disallowed paths"):
            collect(self.worktrees, "worker-alpha", self.artifacts)

    def test_collect_rejects_untracked_source_files_to_prevent_patch_loss(self):
        self.write_manifest()
        prepare(self.repo, self.manifest, self.worktrees)
        worktree = self.worktrees / "worker-alpha"
        (worktree / "new_module.py").write_text("VALUE = 7\n", encoding="utf-8")
        control = worktree / ".qudron-worker"
        control.mkdir()
        result = {
            "schema_version": 1, "task_id": "worker-alpha", "status": "completed",
            "summary": "Created a new module.", "base_sha": self.base,
            "head_sha": self.base, "changed_files": ["new_module.py"],
            "tests": [], "risks": [], "requires_human_review": True,
        }
        (control / "result.json").write_text(json.dumps(result), encoding="utf-8")
        with self.assertRaisesRegex(WorktreeError, "stage them before collection"):
            collect(self.worktrees, "worker-alpha", self.artifacts)

    def test_collect_rejects_invalid_task_id_before_path_lookup(self):
        with self.assertRaisesRegex(WorktreeError, "task_id must match"):
            collect(self.worktrees, "../outside", self.artifacts)


if __name__ == "__main__":
    unittest.main()
