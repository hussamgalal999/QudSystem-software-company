"""
Smart Surrogate System for Qudron Swarm.
Handles proactive failover and state handover between different AI engines.
"""
from __future__ import annotations

import logging
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from unified_intelligence import UnifiedIntelligence

class SmartSurrogate:
    def __init__(self, intel: UnifiedIntelligence):
        self.intel = intel
        self.logger = logging.getLogger("qudron.surrogate")

    def execute_with_failover(self, task_id: str, initial_platform: str, prompt: str, worktree: Path) -> Dict[str, Any]:
        current_platform = initial_platform
        platforms_tried = set()

        while current_platform:
            platforms_tried.add(current_platform)
            self.logger.info(f"Executing task {task_id} on {current_platform}")
            
            result = self.intel.router.route_task(task_id, current_platform, prompt, worktree)
            
            if result["success"]:
                # Success! Update context and return
                self.intel.update_task_context(task_id, current_platform, {"status": "success", "last_result": result["output"]}, ["Task complete"])
                return result
            
            # Failure or Token Exhaustion
            error = result.get("error", "Unknown error")
            self.logger.warning(f"Platform {current_platform} failed: {error}")
            
            # Record failure in context bus
            self.intel.update_task_context(task_id, current_platform, {"status": "failed", "error": error}, ["Retry with surrogate"])
            
            # Find next best platform
            next_platform = self.intel.token_manager.get_best_platform(current_platform)
            
            if next_platform in platforms_tried:
                # No more platforms to try
                self.logger.error(f"All platforms failed for task {task_id}")
                return {"success": False, "error": "All platforms failed or exhausted"}
            
            # Prepare handover context for the next platform
            handover = self.intel.prepare_handover(task_id, current_platform)
            self.logger.info(f"Handing over from {current_platform} to {next_platform}")
            
            # Update prompt with handover info (lessons, state, next steps)
            prompt = self._enrich_prompt(prompt, handover)
            current_platform = next_platform

        return {"success": False, "error": "No platform available"}

    def _enrich_prompt(self, base_prompt: str, handover: Dict[str, Any]) -> str:
        task_id = handover.get("task_id")
        situation_room = self.intel.get_situation_room(task_id)
        
        enriched = f"""
{base_prompt}

--- GLOBAL SWARM CONTEXT (CONTINUE WORK FROM HERE) ---
{situation_room}

IMPORTANT: You are part of a coordinated swarm. Do not repeat work already done by 
other agents listed in the Agent Status Registry. Pick up from the 'Next Coordinated Steps'.
--- END CONTEXT ---
"""
        return enriched
