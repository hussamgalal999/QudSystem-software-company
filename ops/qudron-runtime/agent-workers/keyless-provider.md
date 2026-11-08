# Keyless Provider Strategy — بدون أي مفاتيح

## الحل الموجود بالفعل في مستودعك

`Dockerfile.freellm` + `freelm==0.5.2` هو proxy يجمع **28+ مزود مجاني**
خلف endpoint OpenAI-compatible واحد على `http://localhost:4000/v1`.

### Keyless تماماً (لا تسجيل، لا بريد):
| المزود | النماذج | حد الاستخدام |
|---|---|---|
| `llm7.io` | Llama 3.1 70B, Qwen | غير محدود عملياً |
| `Kilo AI` | Llama 3, Mistral | keyless tier |
| `OVH AI Endpoints` | Llama, Mistral | keyless tier |
| `AI Horde` | 100+ نموذج | anonymous key تلقائي |

### مجاني بتسجيل 2 دقيقة (لا بطاقة):
| المزود | النماذج | الحد |
|---|---|---|
| `Groq` | Llama 3.3 70B, DeepSeek | 30 RPM, 6K RPD |
| `Cerebras` | Llama 3.1 70B | 30 RPM |
| `NVIDIA NIM` | Llama 3.1 70B | 40 RPD |
| `GitHub Models` | GPT-4o-mini, Llama | مجاني لحسابات GitHub |
| `Cloudflare AI` | Llama, Mistral | 10K/يوم |
| `Mistral` | mistral-small | free tier |

## كيف تشغّله الآن

### الطريقة 1: Docker (الأسرع والأنظف)
```bash
# شغّل freelm proxy محلياً
docker run -d --name qudron-freellm \
  -p 4000:4000 \
  -e FREELM_KEYLESS=auto \
  $(docker build -q -f ops/qudron-runtime/Dockerfile.freellm ops/qudron-runtime)

# اختبر فوراً
curl http://localhost:4000/health
```

### الطريقة 2: pip مباشرة (بدون Docker)
```bash
pip install "freelm==0.5.2"
FREELM_KEYLESS=auto freelm serve --port 4000
```

### الطريقة 3: docker-compose (الموجود في المستودع)
```bash
cd ops/qudron-runtime
cp .env.example .env
# اترك كل شيء فارغاً — FREELM_KEYLESS=auto يعمل بدون أي key
docker compose up freellm
```

## ربط agent_fleet.py بـ freelm

بعد تشغيل freelm على port 4000، عدّل أي task manifest ليستخدم `codex` مع:

```bash
export OPENAI_BASE_URL=http://localhost:4000/v1
export OPENAI_API_KEY=keyless  # أي قيمة، freelm يتجاهلها في keyless mode
```

أو في `.env`:
```
LLM_BASE_URL=http://localhost:4000/v1
LLM_API_KEY=keyless
FREELM_KEYLESS=auto
```

## للعمل وجهازك مغلق (GitHub Actions)

```yaml
- name: Start FreeLLM proxy (keyless)
  run: |
    docker build -f ops/qudron-runtime/Dockerfile.freellm \
      -t qudron-freellm ops/qudron-runtime
    docker run -d --name freellm \
      -p 4000:4000 \
      -e FREELM_KEYLESS=auto \
      qudron-freellm
    # انتظر حتى يجهز
    for i in $(seq 1 15); do
      curl -sf http://localhost:4000/health && break
      sleep 2
    done
  
- name: Run agent fleet via FreeLLM
  env:
    OPENAI_BASE_URL: http://localhost:4000/v1
    OPENAI_API_KEY: keyless
    QUDRON_FLEET_HOME_ROOT: /tmp/fleet-home
  run: |
    python ops/qudron-runtime/scripts/agent_fleet.py \
      --manifest ops/qudron-runtime/agent-workers/qudron-fleet-tasks.json \
      --worktree-root /tmp/fleet-worktrees \
      --artifact-dir /tmp/fleet-artifacts
```

## الحصص المجمّعة (keyless فقط)

```
llm7.io        → غير محدود (سرعة متوسطة)
AI Horde       → غير محدود (موزع على المجتمع)  
Kilo keyless   → محدود لكن مجاني
OVH keyless    → محدود لكن مجاني
─────────────────────────────────────────
المجموع التقديري keyless: ~500M token/شهر
```

إضافة Groq + Cerebras (تسجيل 2 دقيقة لكل منهما، لا بطاقة):
```
Groq Llama 3.3 70B → 6,000 req/يوم = ~6M token/يوم
Cerebras Llama 3   → محدود لكن سريع جداً
─────────────────────────────────────────
المجموع مع التسجيل: ~1.7B token/شهر
```
