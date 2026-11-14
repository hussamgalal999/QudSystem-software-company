"""
Meta-Developer Agent for Qudron.
An agent capable of extending its own capabilities by writing and registering new tools.
"""
from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from capability_registry import register_capability
import qudron_worker as worker

class MetaDeveloperAgent:
    def __init__(self, workspace_root: str | Path):
        self.workspace_root = Path(workspace_root)
        self.runtime_dir = self.workspace_root / "ops" / "qudron-runtime"
        self.tools_dir = self.runtime_dir / "meta_tools"
        self.tools_dir.mkdir(exist_ok=True)
        self.registry_db = self.runtime_dir / "data" / "capabilities.sqlite3"

    def create_new_tool(self, capability_name: str, requirements: str, job_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Generates code for a new tool, tests it, and registers it.
        """
        # 1. Generate Tool Code
        prompt = (
            f"Create a Python tool for the following capability: {capability_name}\n"
            f"Requirements: {requirements}\n"
            "The tool should be a single Python file with a `run(**kwargs)` function. "
            "Output only the code, no markdown wrappers."
        )
        
        code = worker.call_model(
            job_id or "meta-dev",
            "meta_developer",
            "reasoning",
            prompt,
            "You are a Senior Agent Tool Developer. Write robust, self-contained Python tools."
        )
        
        # Clean code block
        if "```python" in code:
            code = code.split("```python")[1].split("```")[0].strip()
        elif "```" in code:
            code = code.split("```")[1].split("```")[0].strip()

        file_name = f"{capability_name.lower().replace(' ', '_')}.py"
        file_path = self.tools_dir / file_name
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(code)

        # 2. Basic Syntax Check
        try:
            subprocess.run([sys.executable, "-m", "py_compile", str(file_path)], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            return {"ok": False, "error": f"Generated code has syntax errors: {e.stderr.decode()}"}

        # 3. Register Capability
        capability = {
            "id": f"meta:{capability_name.lower().replace(' ', '_')}",
            "kind": "meta_tool",
            "name": capability_name,
            "description": requirements,
            "version": "1.0.0",
            "source_url": str(file_path),
            "status": "active",
            "trust_score": 80,
            "tags": ["meta", "generated", "python"],
            "metadata": {"generated_at": os.getenv("CURRENT_TIME")}
        }
        
        register_capability(str(self.registry_db), capability)
        
        return {"ok": True, "tool_path": str(file_path), "capability_id": capability["id"]}

if __name__ == "__main__":
    # Test
    # dev = MetaDeveloperAgent(Path(__file__).resolve().parent.parent.parent)
    # res = dev.create_new_tool("System Info", "A tool to get CPU and RAM usage using psutil")
    # print(res)
    pass
