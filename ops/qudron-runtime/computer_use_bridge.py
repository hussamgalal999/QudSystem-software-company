"""
Bridge to the Computer Use Engine (CCUE) binary.
Allows Python agents to execute high-speed computer actions.
"""
from __future__ import annotations

import json
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

class CCUEBridge:
    def __init__(self, binary_path: str | Path):
        self.binary_path = Path(binary_path)
        self.proc: Optional[subprocess.Popen] = None

    def _ensure_started(self):
        if self.proc and self.proc.poll() is None:
            return
        
        self.proc = subprocess.Popen(
            [str(self.binary_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        
        # Wait for ready signal
        for line in self.proc.stdout:
            if "__ready__" in line:
                break

    def call(self, cmd: str, args: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
        self._ensure_started()
        
        request_id = uuid.uuid4().hex
        request = {"id": request_id, "cmd": cmd, "args": args}
        
        try:
            self.proc.stdin.write(json.dumps(request) + "\n")
            self.proc.stdin.flush()
            
            # Read response (assuming one JSON line per response)
            line = self.proc.stdout.readline()
            if not line:
                return {"ok": False, "error": "No response from CCUE"}
                
            response = json.loads(line)
            if response.get("id") == request_id:
                return response
            return {"ok": False, "error": "Response ID mismatch"}
            
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def shutdown(self):
        if self.proc:
            self.proc.terminate()
            self.proc = None

# Default instance path from Documents project
DEFAULT_CCUE_PATH = Path(r"C:\Users\Hossam Galal\Documents\Qudron\scripts\cu-core\target\release\cu-core.exe")

def get_ccue() -> CCUEBridge:
    return CCUEBridge(DEFAULT_CCUE_PATH)
