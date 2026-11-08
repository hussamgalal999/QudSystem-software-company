# Qudron Local Agent Fleet — الميثاق المعماري الموحد

**تاريخ الاعتماد:** 2026-11-08  
**الحالة:** نشط — جميع الوكلاء الأربعة مسجلون في البورد

---

## 1. الوكلاء الأربعة وأدوارهم + الوكلاء المناوبون (Standby Surrogates)

| الوكيل | الدور | يكتب | يراجع | الوكلاء المناوبون عند نفاد التوكنز / الخمول |
|---|---|---|---|---|
| **kiro** | Frontend / Components / UI / Orchestration | ✅ | ✅ | `claude-cli`, `github-copilot`, `antigravity` |
| **github-copilot** | Architecture / Tests / Review / Security | ✅ | ✅ | `antigravity`, `codex-cli` |
| **antigravity** | Infra / Terminal / Cloud Router / Host Guard | Infra & Auto | ✅ | `gemini-cli`, `github-copilot` |
| **qoder** | DAG Engine / Fullstack / Python / Backend | ✅ | ❌ | `antigravity`, `opencode`, `gemini-cli` |
| **opencode** (احتياطي) | Execution / Python Scripting / Testing | ✅ | ✅ | `antigravity`, `qoder` |
| **gemini-cli** (احتياطي) | Terminal Automation / Monitoring | ✅ | ✅ | `antigravity` |
| **claude-cli** (احتياطي) | Refactoring / Spec Analysis | ✅ | ✅ | `kiro` |
| **codex-cli** (احتياطي) | Unit Tests / Syntax Corrections | ✅ | ❌ | `github-copilot` |

---

## 2. آلية الاستعاضة التلقائية واستئناف العمل (Surrogate Resumption)
- **منع توقف العمل عند نفاد التوكنز**: عندما تنفد توكنز أي وكيل (كما حدث مع Qoder)، لا تتوقف المنظومة؛ يقوم المنسق فوراً بنقل المهمة إلى الوكيل المناوب التالي في جدول `STANDBY_SURROGATES`.
- **الاستئناف الدقيق من نقطة التوقف (Exact Checkpoint Resume)**: يستلم الوكيل المناوب كبسولة المهمة (`TaskCapsule`) مع الفروق غير المكتملة والقواعد المستفادة، ويستأنف العمل فوراً من حيث توقف الوكيل السابق تماماً دون إعادة كتابة الكود من الصفر.

---

## 2. مبادئ الميثاق (غير قابلة للتفاوض)

### 🛡️ Host Semaphore — حارس الجهاز
```
max_concurrent_cli = 1          # عملية CLI ثقيلة واحدة فقط
max_model_calls    = 4          # (رُفع من 16 بعد قياس الذاكرة)
backoff_initial    = 1s → 30s   # exponential backoff تلقائي
timeout            = 300s       # مهلة قصوى قبل الإلغاء
```

### ✍️ Single-Writer Rule
- **كاتب واحد** يملك الملف (عبر `coord.py reserve`)
- **مراجع واحد** مستقل (Copilot أو Antigravity)
- **لا يُستدعى الأربعة** لمراجعة تغيير واحد صغير

### 💊 Compact Task Capsules — < 200 توكن
```json
{
  "id":      "T-001",
  "type":    "coding",
  "owner":   "qoder",
  "files":   ["ops/qudron-runtime/qudron_worker.py"],
  "symbols": ["_call_model", "run_job"],
  "diff":    "إضافة retry logic مع exponential backoff",
  "rules":   ["أغلق sqlite connection قبل tearDown على Windows"],
  "status":  "pending"
}
```
**التوفير:** 80%+ من التوكنز مقارنة بإرسال السجل الكامل.

### 🚌 Zero-Token Context Bus
- السجل الكامل محفوظ **محلياً** في `data/fleet.sqlite3`
- كل وكيل يستلم فقط المقاطع المرتبطة بمهمته الحالية
- لا إرسال سياق قديم = لا هدر في التوكنز

### 🔔 Conditional Wakeup — الاستيقاظ المشروط
```
واجهة رسمية موجودة → استخدمها (coord.py msg / API)
لا واجهة رسمية    → احفظ في الطابور وانتظر التنشيط الطبيعي
لا استيقاظ قسري أبداً
```

---

## 3. مسار تدفق المهمة الكامل

```
المستخدم / Kiro يُنشئ TaskCapsule
           ↓
    FleetCoordinator.submit_task()
           ↓
    DurableTaskQueue.enqueue()    ← SQLite WAL (لا ضياع)
           ↓
    _notify_agent()               ← coord.py msg / PROGRESS.md
           ↓
    الوكيل يستلم ويُشغّل:
    FleetCoordinator.run_task_for_agent()
           ↓
    HostSemaphore.acquire()       ← يضمن واحد فقط
           ↓
    executor(capsule, context)    ← context من ZeroTokenContextBus فقط
           ↓
    queue.complete() + bus.record()
           ↓
    (إذا reviewer موجود) → إرسال كبسولة review للمراجع
```

---

## 4. Cloud Fallback Chain

```
1. Cloudflare Workers AI  ← ops/qudron-cloudflare (10k/يوم مجاناً)
   ↓ فشل؟
2. OpenRouter :free        ← meta-llama/llama-3.3-70b-instruct:free
   ↓ فشل؟
3. المهمة تبقى في الطابور  ← لا crash، لا ضياع
```

**إعداد Cloudflare Workers AI:**
```bash
# في .env فقط — لا تضع في الكود أو GitHub
QUDRON_CF_WORKER_URL=https://qudron-worker.YOUR_SUBDOMAIN.workers.dev
OPENROUTER_API_KEY=sk-or-v1-...
```

---

## 5. إصلاح مشاكل Windows المعروفة

| المشكلة | السبب | الحل المُطبَّق |
|---|---|---|
| `WinError 32` SQLite | Windows يُبقي مقبض الملف مفتوحاً | `conn.close()` صريح قبل أي tearDown |
| `os.chmod 0o077` POSIX | NTFS لا يدعم POSIX permissions | `if sys.platform != 'win32':` |
| `os.mkfifo` | غير مدعوم على Windows | تجاوز الاختبار على win32 |

---

## 6. حالة البورد الحالية

```
الوكلاء المسجلون: antigravity, github-copilot, kiro, qoder ✅
الخطط النشطة: P-0001, P-0002, P-0003, P-0005
seq الحالي: 50
آخر hash: sha256:8a2b061d...
```

---

## 7. الملفات الأساسية للنظام

```
.agent-coordination/
  coord.py              ← بروتوكول التنسيق (51 test, 100% pass)
  board/BOARD.md        ← الحالة الحية المُصدَّرة
  events.jsonl          ← السجل الغير قابل للتعديل

ops/qudron-runtime/
  local_agent_fleet.py  ← النظام الرباعي الكامل (هذا الميثاق)
  qudron_brain.py       ← الدماغ المركزي + SQLite memory
  swarm_engine.py       ← 36 وكيل متخصص + ThreadPoolExecutor
  qudron_worker.py      ← الـ worker الرئيسي + model routing
  data/fleet.sqlite3    ← الطابور المدوَّم + سجل السياق
```

---

## 8. الخطوة التالية

**P-0005 — Local Fleet Activation (تحتاج ACK من Copilot):**

1. `coord.py plan propose` بـ scope = `ops/qudron-runtime/local_agent_fleet.py`
2. Copilot يراجع ويُعطي ACK
3. دمج فرع Copilot + فرع الدماغ المركزي في `feat/fleet-unified`
4. اختبار `pytest ops/qudron-runtime/tests/ -x` على Linux (GitHub Actions)
5. PR للـ main بعد green CI
