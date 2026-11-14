import os
import json
import urllib.request
import uuid

def submit_sample_job():
    url = "http://localhost:8765/jobs"
    token = "qudron-dev-token-1234567890"
    
    payload = {
        "title": "استكشاف نظام كوادريون",
        "prompt": "قم بتحليل هيكل المشروع الحالي وتقديم تقرير عن حالة الوكلاء.",
        "task_type": "research",
        "idempotency_key": f"sample-task-{uuid.uuid4().hex[:8]}"
    }
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            print(f"Job submitted successfully! ID: {data['job']['id']}")
    except Exception as e:
        print(f"Error submitting job: {e}")

if __name__ == "__main__":
    submit_sample_job()
