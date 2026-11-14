"""
Adapters for local AI CLI tools (Claude Code, Codex CLI, Gemini CLI).
Provides a unified interface for the swarm to execute tasks via different engines.
"""
from __future__ import annotations

import os
import subprocess
import json
from pathlib import Path
from typing import Dict, Any, Optional

class BaseCLIAdapter:
    def __init__(self, name: str, binary_path: str):
        self.name = name
        self.binary_path = binary_path

    def is_available(self) -> bool:
        # Check if the command exists using where or Get-Command logic
        try:
            # On Windows, try to see if the command is recognized by the shell
            subprocess.run(["powershell", "-Command", f"Get-Command {self.binary_path}"], capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def run_task(self, prompt: str, worktree_path: Path) -> Dict[str, Any]:
        raise NotImplementedError

class ClaudeCodeAdapter(BaseCLIAdapter):
    def __init__(self):
        super().__init__("claude-code", "claude")

    def run_task(self, prompt: str, worktree_path: Path) -> Dict[str, Any]:
        env = os.environ.copy()
        env["CLAUDE_NON_INTERACTIVE"] = "true"
        try:
            # Use powershell to run the script command
            result = subprocess.run(
                ["powershell", "-Command", f"{self.binary_path} execute '{prompt}'"],
                cwd=worktree_path,
                env=env,
                capture_output=True,
                text=True,
                timeout=300
            )
            return {
                "success": result.returncode == 0,
                "output": result.stdout,
                "error": result.stderr,
                "tokens_estimate": len(prompt + result.stdout) // 4
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

class CodexCLIAdapter(BaseCLIAdapter):
    def __init__(self):
        super().__init__("codex-cli", "codex")

    def run_task(self, prompt: str, worktree_path: Path) -> Dict[str, Any]:
        try:
            result = subprocess.run(
                ["powershell", "-Command", f"{self.binary_path} run --prompt '{prompt}'"],
                cwd=worktree_path,
                capture_output=True,
                text=True,
                timeout=300
            )
            return {
                "success": result.returncode == 0,
                "output": result.stdout,
                "error": result.stderr,
                "tokens_estimate": len(prompt + result.stdout) // 4
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

class GeminiCLIAdapter(BaseCLIAdapter):
    def __init__(self):
        super().__init__("gemini-cli", "gemini")

    def run_task(self, prompt: str, worktree_path: Path) -> Dict[str, Any]:
        try:
            result = subprocess.run(
                [self.binary_path, "plan", prompt],
                cwd=worktree_path,
                capture_output=True,
                text=True,
                timeout=300
            )
            return {
                "success": result.returncode == 0,
                "output": result.stdout,
                "error": result.stderr,
                "tokens_estimate": len(prompt + result.stdout) // 4
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

class CLIAdapterRegistry:
    def __init__(self):
        self.adapters = {
            "claude": ClaudeCodeAdapter(),
            "codex": CodexCLIAdapter(),
            "gemini": GeminiCLIAdapter()
        }

    def get_adapter(self, name: str) -> Optional[BaseCLIAdapter]:
        adapter = self.adapters.get(name)
        if adapter and adapter.is_available():
            return adapter
        return None
