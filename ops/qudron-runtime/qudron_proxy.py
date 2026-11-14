import os
import json
import time
import uuid
import sys
from flask import Flask, request, jsonify, render_template_string
from qudron_agent_live import QudronSmartCentralAgent

# Fix encoding for Windows terminal
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

app = Flask(__name__)
agent = QudronSmartCentralAgent()

# Internal state for dashboard
stats = {
    "total_requests": 0,
    "hybrid_analyses": 0,
    "last_learned_lesson": "No lessons yet.",
    "active_agents": ["kiro", "copilot", "antigravity", "qoder"],
    "uptime": time.time()
}

def safe_log(msg):
    try:
        print(msg)
    except:
        pass

DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Qudron Hybrid Intelligence Dashboard</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #0d1117; color: #c9d1d9; padding: 20px; }
        .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; margin-bottom: 20px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; }
        .stat-val { font-size: 24px; color: #58a6ff; font-weight: bold; }
        .agent-tag { background: #238636; color: white; padding: 2px 8px; border-radius: 12px; font-size: 12px; margin-right: 5px; }
        .lesson { border-left: 4px solid #f85149; padding-left: 10px; font-style: italic; }
        h1 { color: #58a6ff; }
    </style>
    <meta http-equiv="refresh" content="5">
</head>
<body>
    <h1>🐦 Qudron Intelligence Hub</h1>
    <div class="grid">
        <div class="card">
            <h3>Total Requests</h3>
            <div class="stat-val">{{ stats.total_requests }}</div>
        </div>
        <div class="card">
            <h3>Hybrid Swarms</h3>
            <div class="stat-val">{{ stats.hybrid_analyses }}</div>
        </div>
        <div class="card">
            <h3>Uptime</h3>
            <div>{{ (time.time() - stats.uptime) | int }}s</div>
        </div>
    </div>
    
    <div class="card">
        <h3>Active Swarm Agents</h3>
        <div>
            {% for agent in stats.active_agents %}
            <span class="agent-tag">{{ agent }}</span>
            {% endfor %}
        </div>
    </div>

    <div class="card">
        <h3>Last Failure Learning</h3>
        <div class="lesson">{{ stats.last_learned_lesson }}</div>
    </div>

    <div class="card">
        <h3>Connection Info</h3>
        <p>Endpoint: <code>http://localhost:9488/v1</code></p>
        <p>Status: <span style="color: #3fb950;">Active & Fused</span></p>
    </div>
</body>
</html>
"""

@app.route('/', methods=['GET'])
def dashboard():
    # Update last lesson from agent
    if agent.learner.lessons:
        stats["last_learned_lesson"] = agent.learner.lessons[-1]["learned_rule"]
    
    return render_template_string(DASHBOARD_HTML, stats=stats, time=time)

@app.route('/healthz', methods=['GET'])
def healthz():
    return jsonify({"status": "ok", "service": "Qudron Hybrid Intelligence Proxy"}), 200

@app.route('/v1/models', methods=['GET'])
def list_models():
    return jsonify({
        "object": "list",
        "data": [
            {"id": "qudron-hybrid", "object": "model", "created": int(time.time()), "owned_by": "qudron"},
            {"id": "qudron-deepseek", "object": "model", "created": int(time.time()), "owned_by": "qudron"}
        ]
    })

@app.route('/v1/chat/completions', methods=['POST'])
def chat_completions():
    stats["total_requests"] += 1
    try:
        data = request.json
        messages = data.get('messages', [])
        model = data.get('model', 'qudron-hybrid')
        
        if not messages:
            return jsonify({"error": "No messages provided"}), 400
        
        user_query = messages[-1].get('content', '')
        
        safe_log(f"[*] Request for model: {model}")
        
        triggers = ["تحليل", "حل", "solve", "analyze", "research", "استكشاف"]
        is_complex = len(user_query) > 100 or any(t in user_query for t in triggers)
        
        if is_complex:
            stats["hybrid_analyses"] += 1
            safe_log("[*] Running hybrid swarm analysis...")
            result = agent.solve_problem_smartly(user_query)
            answer = result['final_solution']
            
            insights = "\n\n--- [Expert Insights] ---\n"
            for persona, p_data in result['perspectives'].items():
                insights += f"- {p_data['name']}: {p_data['analysis'][:200]}...\n"
            answer += insights
        else:
            safe_log("[*] Running direct cloud AI query...")
            answer = agent.ask_cloud_ai(user_query)
        
        response_id = f"chatcmpl-{uuid.uuid4()}"
        
        return jsonify({
            "id": response_id,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": answer
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": len(user_query) // 4,
                "completion_tokens": len(answer) // 4,
                "total_tokens": (len(user_query) + len(answer)) // 4
            }
        })
    except Exception as e:
        safe_log(f"[!] Error in chat_completions: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.getenv("QUDRON_PROXY_PORT", 9488))
    safe_log(f"Qudron Hybrid Proxy starting on port {port}...")
    app.run(host='0.0.0.0', port=port, debug=False)
