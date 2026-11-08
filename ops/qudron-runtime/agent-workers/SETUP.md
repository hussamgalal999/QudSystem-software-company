# إعداد Agent Fleet — الدليل الكامل

## ما يعمل الآن بدون أي إعداد

- **CI على GitHub Actions**: كل push لـ `main` يُشغّل الـ 389 test على Ubuntu مجاناً
- **Manifest validation**: يتحقق من صحة المهام دون استهلاك quota
- **Dry run**: يُظهر الوكلاء المتاحة دون تشغيلها

---

## لاستخدام ChatGPT (OpenAI API) مع agent_fleet.py

التطبيق ChatGPT Desktop **لا يمكن أتمتته**، لكن `codex` CLI يستخدم نفس الـ account:

### الخطوة الوحيدة:
1. اذهب لـ https://platform.openai.com/api-keys
2. أنشئ key جديد (نفس الـ account الخاص بـ ChatGPT)
3. **محلياً**: أضفه في متغير البيئة:
   ```powershell
   $env:OPENAI_API_KEY = "sk-proj-..."
   ```
4. **في GitHub Actions**: اذهب لـ Settings → Secrets → Actions → أضف `OPENAI_API_KEY`

### تشغيل مهمة محلياً:
```powershell
# تثبيت codex CLI
npm install -g @openai/codex

# إعداد مجلد fleet home (خارج الـ repo)
$env:QUDRON_FLEET_HOME_ROOT = "C:\Users\Hossam Galal\fleet-home"

# تشغيل manifest
python ops/qudron-runtime/scripts/agent_fleet.py `
  --manifest ops/qudron-runtime/agent-workers/qudron-fleet-tasks.json `
  --worktree-root C:\Users\Hossam\fleet-worktrees `
  --artifact-dir C:\Users\Hossam\fleet-artifacts
```

---

## التشغيل السحابي (جهازك مغلق)

### من GitHub.com:
1. اذهب لـ **Actions** → **Qudron Agent Fleet** → **Run workflow**
2. اختر المهام أو اتركها فارغة لتشغيل الكل
3. اضغط **Run workflow**

### ما ينتج:
- `run.json` — نتائج كل مهمة
- `*.patch` — التغييرات (تُراجع يدوياً قبل تطبيقها)
- `*.prompt.md` — الـ prompt المُرسَل لكل وكيل

**مهم:** النتائج تُرفَع كـ artifacts في GitHub Actions. لا شيء يُدمج أو يُرفَع تلقائياً — أنت تراجع وتُطبَّق يدوياً.

---

## الوكلاء المدعومون

| الوكيل | CLI | متغير البيئة | ملاحظة |
|---|---|---|---|
| `codex` | `@openai/codex` | `OPENAI_API_KEY` | نفس حساب ChatGPT |
| `gemini` | `gemini` | `GEMINI_API_KEY` | Gemini CLI (موجود على جهازك) |
| `claude` | `claude` | `ANTHROPIC_API_KEY` | Claude Code CLI |

---

## الحدود الآمنة (لا تُغيَّر)

```
max_parallel = 1          # عملية واحدة فقط في GitHub Actions
HOST_SEMAPHORE = 1        # محلياً: عملية CLI واحدة فقط
لا commit تلقائي         # الـ patches تُطبَّق يدوياً فقط
لا push تلقائي           # أنت تقرر ما يدخل main
```
