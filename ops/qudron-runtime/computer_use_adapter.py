"""
Computer Use Adapter for Qudron.
Unifies visual perception (VisionAdapter) and system interaction (CCUEBridge).
"""
from __future__ import annotations
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, List
from computer_use_bridge import get_ccue, CCUEBridge
from vision_adapter import analyze_image

class ComputerUseAdapter:
    def __init__(self, workspace_root: str | Path):
        self.workspace_root = Path(workspace_root)
        self.ccue = get_ccue()
        self.inbox_images = self.workspace_root / "ops" / "qudron-runtime" / "data" / "inbox" / "images"
        self.inbox_images.mkdir(parents=True, exist_ok=True)
        # Set environment variable for vision_adapter safety check
        os.environ["QUDRON_IMAGE_ROOT"] = str(self.inbox_images)

    def take_screenshot(self) -> Path:
        """Takes a screenshot using CCUE and returns the path."""
        screenshot_path = self.inbox_images / f"screenshot_{int(time.time())}.png"
        res = self.ccue.call("screenshot", {"path": str(screenshot_path)})
        if not res.get("ok"):
            raise RuntimeError(f"Failed to take screenshot: {res.get('error')}")
        return screenshot_path

    def observe_and_act(self, goal: str, job_id: Optional[str] = None) -> str:
        """
        Observes the screen, analyzes it based on the goal, and decides the next action.
        This is a single step in a feedback loop.
        """
        # 1. Capture current state
        img_path = self.take_screenshot()
        
        # 2. Vision analysis
        prompt = (
            f"Current Goal: {goal}\n"
            "Analyze the screenshot. Identify the locations (x, y coordinates) of relevant UI elements. "
            "Suggest the next exact CCUE command (click, type, scroll, wait) to move closer to the goal. "
            "Output your reasoning first, then the command in JSON format: "
            '{"action": "click", "x": 100, "y": 200} or {"action": "type", "text": "hello"}.'
        )
        
        analysis = analyze_image(str(img_path), prompt, job_id=job_id)
        return analysis

    def execute_action(self, action_json: str) -> Dict[str, Any]:
        """Parses and executes a command suggested by the vision analyst."""
        import json
        try:
            # Simple extraction if LLM wrapped it in markdown
            if "```json" in action_json:
                action_json = action_json.split("```json")[1].split("```")[0].strip()
            elif "{" in action_json:
                action_json = action_json[action_json.find("{"):action_json.rfind("}")+1]
            
            action = json.loads(action_json)
            cmd = action.get("action")
            args = {k: v for k, v in action.items() if k != "action"}
            
            return self.ccue.call(cmd, args)
        except Exception as e:
            return {"ok": False, "error": f"Failed to parse or execute action: {str(e)}"}

if __name__ == "__main__":
    # Quick test
    adapter = ComputerUseAdapter(Path(__file__).resolve().parent.parent.parent)
    print("Taking screenshot...")
    path = adapter.take_screenshot()
    print(f"Screenshot saved to: {path}")
