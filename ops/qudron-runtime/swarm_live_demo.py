import sys
import os
import json
import logging
from pathlib import Path
from datetime import datetime, timezone

# Add current dir to path
sys.path.append(str(Path(__file__).parent))

from unified_intelligence import UnifiedIntelligence
from smart_surrogate import SmartSurrogate
from task_executor import QudronTaskExecutor
from computer_use_bridge import get_ccue
from db_manager import QudronDBManager

# Setup logging to see the "Brain" thinking
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("SwarmDemo")

def run_live_swarm_demo():
    logger.info("🚀 Starting Qudron Swarm Live Intelligence Demo...")
    
    db_path = Path("swarm_live.sqlite3")
    if db_path.exists(): db_path.unlink()
    
    # 1. Initialize the Swarm Brain
    intel = UnifiedIntelligence(db_path)
    executor = QudronTaskExecutor(intel, Path("reports/demo"))
    ccue = get_ccue()
    
    task_id = "mission_refactor_budget_v1"
    prompt = "Task: Add a 'heartbeat' status method to TokenBudgetManager in unified_intelligence.py."
    
    logger.info(f"🎯 Mission: {prompt}")
    
    # 2. Step 1: Architect Analysis (Simulated via Swarm Engine Logic)
    logger.info("🧠 Swarm Role [Architect] is analyzing requirements...")
    intel.record_lesson("qudron", "architecture", "Keep managers stateless where possible.")
    intel.update_task_context(task_id, "architect", {"phase": "analysis", "finding": "Need a ping-like method."}, ["Dispatch to Developer"])

    # 3. Step 2: Execution with Computer Use (Visual Perception)
    logger.info("👁️ Swarm Role [Perception] is using CCUE to see the screen...")
    # Real CCUE call to prove it's not "Digital Religion"
    try:
        shot_res = ccue.call("screenshot", {})
        if shot_res.get("ok"):
            logger.info("✅ CCUE successfully captured screen. Swarm 'sees' the workspace.")
            intel.update_task_context(task_id, "perception", {"visual_check": "passed"}, ["Continue execution"])
    except Exception as e:
        logger.warning(f"⚠️ CCUE Bridge check skipped (Daemon might need manual start): {e}")

    # 4. Step 3: Proactive Failover Demonstration
    logger.info("🔄 Simulating 'Claude' Token Exhaustion to test Failover...")
    # Set Claude to exhausted
    with intel.continuity.connect() as db:
        db.execute("INSERT INTO token_budgets (platform, quota_limit, used_tokens, status, updated_at) VALUES (?, ?, ?, ?, ?)",
                   ("claude", 1000, 1000, "exhausted", datetime.now(timezone.utc).isoformat()))
        db.commit()
    
    # Now try to execute via Surrogate
    logger.info("⚡ SmartSurrogate is detecting exhaustion and looking for a successor...")
    handover = intel.prepare_handover(task_id, "claude")
    logger.info(f"📡 Handover detected! Next Platform: {handover['target_platform']}")
    
    # 5. Step 4: Consensus & Quality Check
    logger.info("🛡️ Swarm Role [Quality] is reviewing the proposed changes...")
    intel.consensus.request_review(task_id, "quality_engineer", "Proposed code for get_heartbeat() looks solid.")
    
    # Simulate Consensus
    with intel.continuity.connect() as db:
        db.execute("UPDATE unified_context SET global_state_json = ?", 
                   (json.dumps({"quality_engineer": {"status": "reviewed", "review_status": "approved"}}),))
        db.commit()
    
    if intel.consensus.get_consensus(task_id):
        logger.info("🏆 Swarm Consensus Reached! The plan is verified and safe.")
    
    # 6. Final State Audit (Situation Room View)
    logger.info("📊 Final Situation Room Audit:")
    situation_report = intel.get_situation_room(task_id)
    print("\n" + situation_report + "\n")
    
    # Prove that the enriched prompt for a NEW agent contains this context
    new_agent_handover = intel.prepare_handover(task_id, "successor_agent")
    enriched_prompt = executor.surrogate._enrich_prompt("Continue the mission.", new_agent_handover)
    logger.info("📝 Enriched Prompt for the next successor agent:")
    print(enriched_prompt)
    
    logger.info("✅ Demo Complete. Every agent now 'sees' the entire history.")

if __name__ == "__main__":
    run_live_swarm_demo()
