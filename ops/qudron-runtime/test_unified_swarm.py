import sys
from pathlib import Path

# Add current dir to path
sys.path.append(str(Path(__file__).parent))

from unified_intelligence import UnifiedIntelligence
from smart_surrogate import SmartSurrogate
from db_manager import QudronDBManager

def test_unified_swarm():
    db_path = Path("test_swarm.sqlite3")
    if db_path.exists():
        db_path.unlink()
        
    intel = UnifiedIntelligence(db_path)
    surrogate = SmartSurrogate(intel)
    
    # 1. Record a lesson
    intel.record_lesson("test_project", "code", "Always use modular imports in Python refactoring.")
    
    # 2. Update context for a task
    task_id = "task_123"
    intel.update_task_context(task_id, "claude", {"step": 1, "status": "partial", "project": "test_project"}, ["Finalize imports"])
    
    # 3. Prepare handover
    handover = intel.prepare_handover(task_id, "claude")
    print(f"Handover target: {handover['target_platform']}")
    
    # 4. Enrich prompt
    base_prompt = "Refactor this file."
    enriched = surrogate._enrich_prompt(base_prompt, handover)
    print("\n--- Enriched Prompt ---")
    print(enriched)
    
    # 5. Check consensus
    intel.consensus.request_review(task_id, "reviewer_1", "Looks good.")
    # (Simulate review approval)
    with intel.continuity.connect() as db:
        db.execute("UPDATE unified_context SET global_state_json = ?", 
                   (json.dumps({"reviewer_1": {"status": "reviewed", "review_status": "approved"}}),))
    
    is_agreed = intel.consensus.get_consensus(task_id)
    print(f"\nConsensus achieved: {is_agreed}")

if __name__ == "__main__":
    import json
    test_unified_swarm()
