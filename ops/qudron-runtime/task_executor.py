"""
Qudron Task Executor Module.
Handles swarm execution, role assignments, and smart failover using Unified Intelligence.
"""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from smart_surrogate import SmartSurrogate
from unified_intelligence import UnifiedIntelligence
from computer_use_bridge import get_ccue
from swarm_engine import execute_swarm

class QudronTaskExecutor:
    def __init__(self, intel: UnifiedIntelligence, reports_dir: Path):
        self.intel = intel
        self.surrogate = SmartSurrogate(intel)
        self.reports_dir = reports_dir
        self.ccue = get_ccue()

    def execute_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        task_id = job["id"]
        prompt = job["prompt"]
        task_type = job["task_type"]
        
        # 1. Check for existing context (resuming)
        context = self.intel.get_task_context(task_id)
        if context:
            logging.info(f"Resuming task {task_id} from context bus")
            # Handover logic will be handled by surrogate.execute_with_failover
        
        # 2. Execute with Swarm and Smart Failover
        # We wrap the execute_swarm in the surrogate logic
        worktree = self.reports_dir / task_id
        worktree.mkdir(parents=True, exist_ok=True)
        
        # The surrogate will try different platforms (Claude, Codex, Gemini) 
        # and share context between them via the context bus.
        result = self.surrogate.execute_with_failover(
            task_id=task_id,
            initial_platform="claude", # Start with Claude as default
            prompt=prompt,
            worktree=worktree
        )
        
        if result["success"]:
            # Final consensus check if needed
            if self.intel.consensus.get_consensus(task_id):
                logging.info(f"Task {task_id} achieved consensus.")
            
            # Save results
            result_path = worktree / "final_report.md"
            result_path.write_text(result["output"], encoding="utf-8")
            return {"status": "succeeded", "result_path": str(result_path)}
        
        return {"status": "failed", "error": result.get("error")}
