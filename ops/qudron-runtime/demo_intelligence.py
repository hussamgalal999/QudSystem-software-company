import sys
from qudron_agent_live import QudronSmartCentralAgent
import json

def show_qudron_intelligence():
    print("--- Qudron Smart Central Agent Demo ---")
    agent = QudronSmartCentralAgent()
    
    problem = "كيف يمكننا تحسين أداء وكلاء كوادريون عند التعامل مع المهام الطويلة؟"
    
    print(f"Question: {problem}")
    print("\n[Thinking... Combining GitHub, Multi-Persona, and Learning Engines]")
    
    result = agent.solve_problem_smartly(problem)
    
    print("\n--- [Final Solution from Qudron Brain] ---")
    print(result['final_solution'])
    
    print("\n--- [Expert Perspectives] ---")
    for persona_id, p in result['perspectives'].items():
        print(f"\n[{p['name']}]:")
        print(p['analysis'])

if __name__ == "__main__":
    show_qudron_intelligence()
