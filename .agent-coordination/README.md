# Coord Board — Runbook (Qoder ↔ GitHub Copilot)

Absolute board path (identical from every worktree):

```
C:\Users\Hossam Galal\Desktop\Qudron\.agent-coordination
```

`coord.py` is Python-standard-library only. Everything is driven from this directory, so
neither agent has to import code from the other's worktree.

Full rules: [PROTOCOL.md](PROTOCOL.md). Live snapshot: [board/BOARD.md](board/BOARD.md).

## 0. Set a short command

PowerShell:

```powershell
$C = 'C:\Users\Hossam Galal\Desktop\Qudron\.agent-coordination\coord.py'
python $C board
```

cmd.exe:

```bat
set C=C:\Users\Hossam Galal\Desktop\Qudron\.agent-coordination\coord.py
python "%C%" board
```

## 1. First contact (every agent, every session)

```powershell
python $C board                             # 1. read the live board
python $C register --agent github-copilot ` # 2. identity + branch + worktree + base SHA
  --display-name "GitHub Copilot" `
  --branch (git rev-parse --abbrev-ref HEAD) `
  --worktree (git rev-parse --show-toplevel) `
  --base-sha (git rev-parse HEAD)
python $C plan ack --agent github-copilot --plan P-0001   # 3. ACK the plan you will work under
python $C msg send --from github-copilot --to qoder --subject "identity + scope" --body "..."
python $C msg inbox --agent github-copilot  # 4. read the ACK before touching anything
```

## 2. Before every edit

The plan you gate against must declare the paths (`--scope`) and symbols (`--symbols`) you
are about to touch — the gate refuses anything the plan does not cover:

```powershell
python $C plan propose --agent github-copilot --title "my work" --summary "..." `
  --scope path/one.py path/two.py --symbols "Class.method"
python $C reserve --agent github-copilot --plan P-0002 --files path/one.py path/two.py --symbols "Class.method"
python $C gate --agent github-copilot --plan P-0002 --files path/one.py path/two.py --symbols "Class.method"
# ALLOW (exit 0) -> edit.  BLOCK (exit 3) -> resolve, do not edit.
```

## 3. While and after working

```powershell
python $C status set --agent github-copilot --state in_progress --task-id T3 --note "editing parser"
python $C handoff --agent github-copilot --task-id T3 --summary "what changed" --files path/one.py --tests "command + result"
python $C release --agent github-copilot --reservation R-0002
python $C board --write            # refresh board/BOARD.md
python $C verify                   # exit 0 = chain intact
```

To verify whether your outbound plan or message has been acknowledged by a peer, inspect the board state:
```powershell
python coord.py --json board       # look under plan['acked_by'] or msg['acked_by']
```

## 4. Tests

```powershell
python -m unittest discover -s "C:\Users\Hossam Galal\Desktop\Qudron\.agent-coordination\tests" -v
```

The tests always use a throwaway `--root` in `%TEMP%`; they never touch the live board and
never touch `ops/qudron-runtime`.

---

## 5. Paste-ready activation message for GitHub Copilot

Copy the whole block below into the Copilot chat, verbatim, before it edits any file.

```text
[QUD-COORD v1 — تفعيل بروتوكول التنسيق بين Qoder وCopilot]

قبل أي قراءة ملفات للتعديل أو أي كتابة، نفّذ التالي بالترتيب الإلزامي:

1) اقرأ البروتوكول واللوحة:
   - C:\Users\Hossam Galal\Desktop\Qudron\.agent-coordination\PROTOCOL.md
   - C:\Users\Hossam Galal\Desktop\Qudron\.agent-coordination\README.md
   - نفّذ: python "C:\Users\Hossam Galal\Desktop\Qudron\.agent-coordination\coord.py" board

2) سجّل هويتك (agent_id = github-copilot) مع الفرع وworktree وbase SHA الفعلي لمساحة عملك:
   python "...\.agent-coordination\coord.py" register --agent github-copilot ^
     --display-name "GitHub Copilot" --role "<دورك في المهمة>" ^
     --branch "<git rev-parse --abbrev-ref HEAD>" ^
     --worktree "<git rev-parse --show-toplevel>" --base-sha "<git rev-parse HEAD>"

3) أرسل تفاصيلك وخطتك إلى qoder واطلب ACK:
   python "...\coord.py" msg send --from github-copilot --to qoder ^
     --subject "identity + scope" --body "<المهمة، الملفات التي تنوي لمسها، الرموز>"

4) انتظر ACK: نفّذ python "...\coord.py" msg inbox --agent github-copilot
   لا تعدّل أي ملف قبل: (أ) وصول ACK على رسالتك، (ب) ACK خطة العمل (plan ack)،
   (ج) حجز ناجح للمسارات والرموز (reserve)، (د) خروج الأمر gate بحالة ALLOW / exit 0.
   ملاحظة: الخطة يجب أن تعلن المسارات عبر --scope والرموز عبر --symbols، وإلا رفض gate التعديل.

5) أثناء العمل وبعده: status set، ثم handoff، ثم release، ثم board --write، ثم verify.

قيود صارمة:
- لا تعدّل مساراً محجوزاً لـqoder، ولا تلمس worktree الخاص به.
- لا تعدّل events.jsonl يدوياً ولا تحذف أي سطر منه.
- لا تنشئ commit ولا push داخل .agent-coordination.
- إذا خرج gate بحالة BLOCK أو verify بحالة غير سليمة: توقف وأبلغ المستخدم وqoder.
```

Equivalent English instruction (same contract):

```text
Coordination is mandatory. Read .agent-coordination/PROTOCOL.md and the live board,
register your identity (branch, worktree, base SHA), message qoder with your scope,
and WAIT for the ACK. Register your plan tasks with qoder's plan (or propose your own),
reserve the exact paths/symbols, and only edit after `coord.py gate` returns ALLOW.
Never edit a path reserved by qoder, never hand-edit events.jsonl, never commit or push.
```

## 6. Current state of the board

Both agents are registered.

| Agent | Branch | Worktree | Base SHA |
| --- | --- | --- | --- |
| `qoder` | `main` | `C:/Users/Hossam Galal/Desktop/Qudron` | `e1039f4a6ae1` |
| `github-copilot` | `hussamgalal999-compliant-ai-provider-routing` | `C:/Users/Hossam Galal/copilot-worktrees/Qudron/hussamgalal999-cautious-journey` | `847485ebf07f` |

* `P-0001` (copilot) — shared protocol split, fully ACKed by qoder. T1 (qoder) delivered as `H-0001`.
* `P-0002` (qoder) — gate hardening derived from copilot review `M-0002`, **awaiting copilot ACK**.
* `M-0001..M-0003` (copilot) ACKed by qoder; `M-0004` (qoder) replies to the review and asks for the ACK.
* `R-0001..R-0004` — qoder reservations on the board sources and symbols, 240 min lease.

Run `python coord.py board` for the authoritative snapshot; `board/BOARD.md` is the rendered copy.

## 7. Constraints honoured by this directory

* Nothing outside `.agent-coordination` is created or modified.
* No git commit, no push, no branch change.
* Copilot worktrees under `C:\Users\Hossam Galal\copilot-worktrees\Qudron\` are only
  referenced by path, never touched.
* `.agent-coordination` shows up as a single untracked directory; it is not added to
  `.gitignore` because that would mean editing a file outside this directory.
