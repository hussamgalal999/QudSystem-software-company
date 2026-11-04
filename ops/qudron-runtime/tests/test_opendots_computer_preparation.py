import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import prepare_opendots_computers as prepare


class OpenDotsComputerPreparationTests(unittest.TestCase):
    def test_generates_two_tokens_only_when_missing_and_preserves_existing(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "# keep this comment\nCOMPUTER_SUPERVISOR_TOKEN=\nCOMPUTER_TOKEN=existing-token-value-long-enough-000000000000\n"
            )
            generated = prepare.prepare(env_file)
            result = env_file.read_text()
            self.assertEqual(generated, ("COMPUTER_SUPERVISOR_TOKEN",))
            self.assertIn("COMPUTER_TOKEN=existing-token-value-long-enough-000000000000", result)
            token_line = next(line for line in result.splitlines() if line.startswith("COMPUTER_SUPERVISOR_TOKEN="))
            token = token_line.split("=", 1)[1]
            self.assertGreaterEqual(len(token), 48)
            self.assertTrue(env_file.stat().st_mode & 0o077 == 0)

    def test_does_not_rotate_existing_valid_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            first = "a" * 48
            second = "b" * 48
            env_file.write_text(f"COMPUTER_SUPERVISOR_TOKEN={first}\nCOMPUTER_TOKEN={second}\n")
            generated = prepare.prepare(env_file)
            self.assertEqual(generated, ())
            self.assertIn(first, env_file.read_text())
            self.assertIn(second, env_file.read_text())

    def test_creates_missing_docker_network(self):
        calls = []
        def fake_run(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 1 if command[1:3] == ["network", "inspect"] else 0)
        network = prepare.ensure_docker_network("qudron", runner=fake_run)
        self.assertEqual(network, "qudron-computers")
        self.assertEqual(calls, [
            ["docker", "network", "inspect", "qudron-computers"],
            ["docker", "network", "create", "qudron-computers"],
        ])

    def test_reuses_existing_docker_network_without_mutation(self):
        calls = []
        def fake_run(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, 0)
        self.assertEqual(prepare.ensure_docker_network("qudron", runner=fake_run), "qudron-computers")
        self.assertEqual(calls, [["docker", "network", "inspect", "qudron-computers"]])

    def test_rejects_unsafe_network_namespace(self):
        with self.assertRaises(ValueError):
            prepare.ensure_docker_network("../host")


if __name__ == "__main__":
    unittest.main()
