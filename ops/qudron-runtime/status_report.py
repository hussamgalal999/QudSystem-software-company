import sys
import datetime
from pathlib import Path
from unified_intelligence import UnifiedIntelligence

def generate_status_report():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    db_path = Path("data/qudron.sqlite3")
    if not db_path.exists():
        print("Qudron database not found. Please ensure the worker is running.")
        return

    intel = UnifiedIntelligence(db_path)
    
    print("# Qudron System Status Report")
    print(f"Date: {datetime.datetime.now().isoformat()}")
    print("\n## Active Agents & Registry")
    print("- kiro (Frontend/UI)")
    print("- github-copilot (Architecture/Review)")
    print("- antigravity (Infra/Cloud)")
    print("- qoder (Execution/Swarm)")
    
    print("\n## Situation Room (Global)")
    with intel.continuity.connect() as db:
        try:
            row = db.execute("SELECT task_id FROM unified_context ORDER BY updated_at DESC LIMIT 1").fetchone()
            if row:
                print(intel.get_situation_room(row[0]))
            else:
                print("No active tasks in unified context.")
        except:
            print("Unified context table not ready.")

    print("\n## Learned Lessons (Failure Learning System)")
    try:
        with intel.continuity.connect() as db:
            rows = db.execute("SELECT error_context, preventive_rule FROM failure_lessons LIMIT 5").fetchall()
            for r in rows:
                print(f"- **{r[0]}**: {r[1]}")
    except:
        print("No lessons recorded yet.")

    print("\n## Token & Budget Status")
    try:
        with intel.continuity.connect() as db:
            rows = db.execute("SELECT platform, used_tokens, quota_limit, status FROM token_budgets").fetchall()
            for r in rows:
                print(f"- **{r[0]}**: {r[1]}/{r[2]} tokens ({r[3]})")
    except:
        print("Budget data not available.")

if __name__ == "__main__":
    generate_status_report()
