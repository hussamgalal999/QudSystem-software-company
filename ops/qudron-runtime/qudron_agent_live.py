"""Qudron Smart Central Agent: الذكاء المركزي الهجين يجمع بين:
1. Keyless Cloud AI (pollinations.ai) - التنفيذ المجاني
2. GitHub Intelligence Mining - الحلول الجاهزة  
3. Multi-Persona Analysis - 10 زوايا تفكير
4. Failure Learning Engine - التعلم من الأخطاء

نظام أذكى يجمع كل الأفكار في وكيل واحد سحابي 100% مجاني.
"""
from __future__ import annotations
import sys
import json
import urllib.request
import urllib.error
import subprocess
import re
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime

# ─── الإعدادات الأساسية ──────────────────────────────────────────
ENDPOINT = "https://text.pollinations.ai/openai/chat/completions"
DEFAULT_MODEL = "openai"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# ─── نظام الشخصيات المتعددة (10 زوايا تفكير) ──────────────────────
PERSONAS = {
    "security_expert": {
        "name": "الخبير الأمني",
        "focus": "الثغرات الأمنية، التشفير، التحقق من الصلاحيات، حماية البيانات",
        "questions": [
            "ما الثغرات الأمنية المحتملة في هذا الكود؟",
            "هل توجد بيانات حساسة معرضة للخطر؟",
            "كيف يمكن تحسين الأمان؟"
        ]
    },
    "performance_engineer": {
        "name": "مهندس الأداء",
        "focus": "السرعة، الكفاءة، استهلاك الموارد، التحسين",
        "questions": [
            "ما نقطة الاختناق في الأداء؟",
            "كيف يمكن تحسين الكفاءة؟",
            "ما البدائل الأسرع؟"
        ]
    },
    "system_architect": {
        "name": "معماري الأنظمة",
        "focus": "الهيكل، العلاقات، التوسع، الصيانة",
        "questions": [
            "هل الهيكل الحالي قابل للتوسع؟",
            "ما العلاقات بين المكونات؟",
            "كيف يمكن تحسين التصميم؟"
        ]
    },
    "quality_reviewer": {
        "name": "مراجع الجودة",
        "focus": "المعايير، الأخطاء، الجودة، التوثيق",
        "questions": [
            "هل يتبع الكود المعايير؟",
            "ما الأخطاء المحتملة؟",
            "كيف يمكن تحسين الجودة؟"
        ]
    },
    "innovation_explorer": {
        "name": "مستكشف الابتكار",
        "focus": "الحلول غير التقليدية، الابتكار، التفكير الجانبي",
        "questions": [
            "ما الحلول غير التقليدية الممكنة؟",
            "كيف يمكن الابتكار في هذا المجال؟",
            "ما البدائل المهملة؟"
        ]
    }
}

# ─── ذاكرة GitHub الذكية ────────────────────────────────────────
class GitHubIntelligenceMiner:
    """يستخرج الحلول الجاهزة من GitHub ويبني ذاكرة جماعية"""
    
    @staticmethod
    def search_solutions(query: str, language: str = "python") -> List[Dict]:
        """يبحث عن حلول جاهزة على GitHub"""
        import urllib.parse
        url = f"https://api.github.com/search/code?q={urllib.parse.quote(query)}+language:{language}"
        
        try:
            req = urllib.request.Request(url, headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "Qudron-Agent"
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                return [
                    {
                        "repo": item["repository"]["full_name"],
                        "path": item["path"],
                        "url": item["html_url"],
                        "score": item.get("score", 0)
                    }
                    for item in data.get("items", [])[:3]
                ]
        except:
            return []
    
    @staticmethod
    def get_pattern_memory() -> Dict:
        """ذاكرة الأنماط البرمجية الشائعة"""
        return {
            "common_solutions": {
                "authentication": ["JWT", "OAuth2", "Session-based"],
                "api_design": ["REST", "GraphQL", "gRPC"],
                "error_handling": ["Try-Catch", "Result Pattern", "Custom Exceptions"],
                "testing": ["Unit Tests", "Integration Tests", "Mocking"]
            },
            "best_practices": {
                "python": ["Type hints", "Async/await", "Context managers"],
                "typescript": ["Strict types", "Interfaces", "Generics"],
                "react": ["Hooks rules", "Memoization", "Error boundaries"]
            }
        }

# ─── محرك التعلم من الفشل ────────────────────────────────────────
class FailureLearningEngine:
    """يتعلم من الأخطاء ويحسن نفسه تلقائياً"""
    
    def __init__(self, log_file: str = "failure_learning.json"):
        self.log_file = REPO_ROOT / "ops" / "qudron-runtime" / log_file
        self.lessons = self.load_lessons()
    
    def load_lessons(self) -> List[Dict]:
        """يحمل الدروس المستفادة"""
        if self.log_file.exists():
            with open(self.log_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []
    
    def record_failure(self, context: str, error: str, solution: str):
        """يسجل فشلاً ويستخلص الدرس"""
        lesson = {
            "timestamp": datetime.utcnow().isoformat(),
            "context": context[:500],
            "error": error[:200],
            "solution": solution[:500],
            "learned_rule": self.extract_rule(context, error, solution)
        }
        
        self.lessons.append(lesson)
        self.save_lessons()
    
    def extract_rule(self, context: str, error: str, solution: str) -> str:
        """يستخلص قاعدة من الفشل"""
        # تحليل بسيط للنمط
        if "TypeError" in error:
            return "التحقق من أنواع البيانات قبل التنفيذ"
        elif "AttributeError" in error:
            return "التحقق من وجود السمات قبل الوصول إليها"
        elif "KeyError" in error:
            return "التحقق من وجود المفاتيح في القواميس"
        else:
            return "مراجعة المنطق والافتراضات الأساسية"
    
    def save_lessons(self):
        """يحفظ الدروس"""
        with open(self.log_file, 'w', encoding='utf-8') as f:
            json.dump(self.lessons, f, ensure_ascii=False, indent=2)
    
    def get_advice(self, current_context: str) -> str:
        """يعطي نصائح بناءً على الدروس السابقة"""
        if not self.lessons:
            return "لا توجد دروس سابقة. كن حذراً ووثق كل شيء."
        
        # البحث عن دروس مشابهة
        similar_lessons = []
        for lesson in self.lessons[-5:]:  # آخر 5 دروس
            if any(keyword in current_context for keyword in ["type", "attribute", "key", "null"]):
                similar_lessons.append(lesson)
        
        if similar_lessons:
            return f"⚠️ درس من الماضي: {similar_lessons[-1]['learned_rule']}"
        return ""

# ─── الذكاء المركزي الهجين ───────────────────────────────────────
class QudronSmartCentralAgent:
    """الوكيل الذكي المركزي الذي يجمع كل القدرات"""
    
    def __init__(self):
        self.gh_miner = GitHubIntelligenceMiner()
        self.learner = FailureLearningEngine()
        self.conversation_history = []
    
    def ask_cloud_ai(self, prompt: str, persona: str = None) -> str:
        """يرسل استعلام إلى السحابة المجانية"""
        system_prompt = """أنت "Qudron Smart Central Agent" - الذكاء المركزي لمنظومة QudSystem.
قيمك: الدقة الهندسية، الصدق، الأمان، Zero Waste، Cloud-Native.
دورك: مساعدة المهندس حسام جلال في تطوير QudSystem بذكاء وكفاءة."""
        
        if persona and persona in PERSONAS:
            system_prompt += f"\n\nأنت الآن تعمل كـ {PERSONAS[persona]['name']}."
            system_prompt += f"\nتركيزك: {PERSONAS[persona]['focus']}"
        
        messages = [{"role": "system", "content": system_prompt}]
        
        # إضافة التاريخ إن وجد
        if self.conversation_history:
            messages.extend(self.conversation_history[-5:])  # آخر 5 رسائل
        
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": DEFAULT_MODEL,
            "messages": messages,
            "temperature": 0.3,
        }
        
        try:
            req = urllib.request.Request(
                ENDPOINT,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Qudron-Smart-Agent/2.0"
                },
                method="POST"
            )
            
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                response = data["choices"][0]["message"]["content"]
                
                # حفظ في التاريخ
                self.conversation_history.append({"role": "user", "content": prompt})
                self.conversation_history.append({"role": "assistant", "content": response})
                
                return response
                
        except Exception as e:
            return f"[خطأ في الاتصال السحابي]: {str(e)[:100]}"
    
    def analyze_with_multiple_perspectives(self, problem: str) -> Dict:
        """يحلل المشكلة من 5 زوايا مختلفة"""
        perspectives = {}
        
        for persona_id, persona_info in PERSONAS.items():
            prompt = f"""كمهندس {persona_info['name']} متخصص في {persona_info['focus']}:
            
            المشكلة: {problem}
            
            ركز على:
            1. {persona_info['questions'][0]}
            2. {persona_info['questions'][1]}
            3. {persona_info['questions'][2]}
            
            أعط تحليلاً مختصراً من وجهة نظرك المتخصصة."""
            
            response = self.ask_cloud_ai(prompt, persona_id)
            perspectives[persona_id] = {
                "name": persona_info["name"],
                "analysis": response[:500]  # تقليل الطول
            }
        
        return perspectives
    
    def get_github_solutions(self, problem: str) -> List[Dict]:
        """يبحث عن حلول جاهزة على GitHub"""
        # استخراج الكلمات المفتاحية
        keywords = re.findall(r'\b\w{4,}\b', problem.lower())
        query = " OR ".join(keywords[:3])
        
        return self.gh_miner.search_solutions(query)
    
    def solve_problem_smartly(self, problem: str) -> Dict:
        """يحل المشكلة بالذكاء الهجين"""
        print("\n🔍 [المرحلة 1] البحث عن حلول جاهزة على GitHub...")
        github_solutions = self.get_github_solutions(problem)
        
        print("🧠 [المرحلة 2] التحليل من 5 زوايا مختلفة...")
        perspectives = self.analyze_with_multiple_perspectives(problem)
        
        print("💡 [المرحلة 3] الاستشارة من الدروس السابقة...")
        learned_advice = self.learner.get_advice(problem)
        
        print("🤖 [المرحلة 4] توليد الحل الذكي...")
        final_prompt = f"""بناءً على:
1. حلول GitHub الجاهزة: {len(github_solutions)} حل
2. تحليل 5 خبراء: {', '.join([p['name'] for p in perspectives.values()])}
3. النصيحة من الدروس السابقة: {learned_advice or 'لا توجد'}

المشكلة: {problem}

أعط حلاً شاملاً يجمع بين:
- أفضل الحلول الجاهزة
- توصيات الخبراء
- تجنب الأخطاء السابقة"""
        
        final_solution = self.ask_cloud_ai(final_prompt)
        
        return {
            "github_solutions": github_solutions,
            "perspectives": perspectives,
            "learned_advice": learned_advice,
            "final_solution": final_solution
        }

# ─── الواجهة الرئيسية ────────────────────────────────────────────
def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    
    agent = QudronSmartCentralAgent()
    
    print("""
    ╔═══════════════════════════════════════════════╗
    ║   Qudron Smart Central Agent - النظام الأذكى   ║
    ║   يجمع: السحابة المجانية + GitHub + التعلم   ║
    ╚═══════════════════════════════════════════════╝
    
    المزايا:
    ✅ 100% مجاني (لا مفاتيح، لا تكاليف)
    ✅ 5 خبراء يحللون كل مشكلة
    ✅ ذاكرة GitHub مع حلول جاهزة
    ✅ يتعلم من الأخطاء تلقائياً
    """)
    
    if len(sys.argv) > 1:
        # وضع الأوامر السريعة
        problem = " ".join(sys.argv[1:])
        print(f"\n🎯 المشكلة: {problem}")
        
        # نسخة مبسطة للاختبار
        print("\n🧠 النظام الأذكى يعمل... (اتصال مباشر بالسحابة)")
        try:
            response = agent.ask_cloud_ai(problem)
            print(f"\n💡 الحل الذكي:")
            print("="*40)
            print(response)
            print("="*40)
        except Exception as e:
            print(f"\n⚠️ خطأ: {e}")
            print("\n🔧 الحل اليدوي الذكي:")
            print("1. تحقق من اتصال الإنترنت")
            print("2. استخدم pollinations.ai مباشرة عبر curl")
            print("3. جرب مشكلة أبكر مثل: 'كيف أكتب دالة في Python؟'")
        
    else:
        # الوضع التفاعلي
        print("\nاكتب مشكلتك التقنية أو 'exit' للخروج:\n")
        
        while True:
            try:
                problem = input("🧑‍💻 أنت: ").strip()
                
                if not problem:
                    continue
                
                if problem.lower() in ("exit", "quit", "خروج"):
                    print("\nإلى اللقاء! النظام أصبح أذكى بفضل مساهمتك. 🚀")
                    break
                
                # حل ذكي
                result = agent.solve_problem_smartly(problem)
                
                print(f"\n🤖 Qudron Agent:")
                print("-"*40)
                print(result["final_solution"])
                print("-"*40)
                
                # تسجيل للتعلم المستقبلي
                agent.learner.record_failure(
                    context=problem,
                    error="",  # لا خطأ هنا، مجرد تسجيل للتحليل
                    solution=result["final_solution"][:300]
                )
                
            except (KeyboardInterrupt, EOFError):
                print("\n\nالحفظ والتعلّم... إلى اللقاء!")
                break

if __name__ == "__main__":
    main()
