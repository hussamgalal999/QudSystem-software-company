"""Qudron Live Agent: First Autonomous Keyless Cloud Agent for QudSystem.

Connects to a 100% free, zero-key, cloud-based inference provider.
Uses zero local compute and requires zero API keys.
"""
from __future__ import annotations
import sys
import json
import urllib.request
import urllib.error

ENDPOINT = "https://text.pollinations.ai/openai/chat/completions"
DEFAULT_MODEL = "openai"

SYSTEM_PROMPT = """أنت "Qudron Agent 01" (الوكيل الذكي الأول لمنظومة Qudron و QudSystem.Ltd).
أنت معمار ذكاء اصطناعي ومهندس برمجيات مستقل تابع لشركة QudSystem بقيادة المهندس حسام جلال.
قيمك الأساسية:
- الدقة الهندسية، الصدق، الأمان، وتوفير الموارد (Zero Waste).
- تعمل سحابياً بالكامل (Cloud-Native) دون استهلاك موارد جهاز المستخدم.
- دورك هو مساعدة المهندس في تطوير منتجات QudSystem (مثل Qudron, CVPen, Dragon R1/B1) ومراجعة الأكواد والتخطيط.
تحدث باللغة العربية باحترافية، وكن جاهزاً لتقديم حلول وأكواد فورية ودقيقة."""

def ask_agent(prompt: str, model: str = DEFAULT_MODEL, history: list[dict] | None = None) -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
    }

    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Qudron-Agent-Live/1.0"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        return f"[خطأ سحابي HTTP {e.code}]: تعذر الاتصال بمزود الذكاء."
    except Exception as e:
        return f"[خطأ في الاتصال]: {e}"

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if len(sys.argv) > 1:
        user_query = " ".join(sys.argv[1:])
        print(f"\n[سؤال للمستخدم]: {user_query}\n")
        response = ask_agent(user_query)
        print(f"[رد Qudron Agent 01]:\n{response}\n")
    else:
        print("=== Qudron Live Keyless Cloud Agent ===")
        print("الوكيل السحابي الأول لـ QudSystem يعمل الآن مجاناً 100% بدون أي مفاتيح!")
        print("اكتب سؤالك أو 'exit' للخروج:\n")
        while True:
            try:
                query = input("أنت: ").strip()
                if not query:
                    continue
                if query.lower() in ("exit", "quit", "خروج"):
                    print("إلى اللقاء يا هندسة!")
                    break
                reply = ask_agent(query)
                print(f"\nQudron Agent 01:\n{reply}\n")
            except (KeyboardInterrupt, EOFError):
                break
