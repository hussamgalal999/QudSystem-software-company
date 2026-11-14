import tempfile
import unittest
from pathlib import Path

from self_critique_engine import analyze_python_file, run_self_critique


class SelfCritiqueEngineTests(unittest.TestCase):
    def test_analyze_python_file_detects_bare_except_and_long_function(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "sample.py"
            body = "\n".join(["    x = 1"] * 145)
            target.write_text(
                f"def huge():\n{body}\n    try:\n        return x\n    except:\n        return 0\n",
                encoding="utf-8",
            )
            metrics = analyze_python_file(target, root)
            self.assertEqual(metrics.bare_excepts, 1)
            self.assertGreater(metrics.max_function_lines, 140)

    def test_run_self_critique_on_qudron_produces_compact_capsule(self):
        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        report = run_self_critique(repo_root)
        self.assertGreater(report.modules_scanned, 10)
        capsule = report.to_compact_capsule(max_chars=1200)
        self.assertLessEqual(len(capsule), 1200)
        self.assertGreaterEqual(report.efficiency_score, 0)
        self.assertLessEqual(report.efficiency_score, 100)


if __name__ == "__main__":
    unittest.main()
