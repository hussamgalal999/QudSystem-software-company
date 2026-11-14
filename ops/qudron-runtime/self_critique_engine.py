#!/usr/bin/env python3
"""
Qudron Zero-Token Self-Critique & Continuous Evolution Engine
=============================================================
Performs deterministic AST, test-health, token-efficiency, and coordination
self-critique using 0 LLM tokens first, emitting a compact (<1200 char)
critique capsule and a detailed Markdown report for periodic GitHub Actions
or local autonomous cycles.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ModuleMetrics:
    path: str
    lines: int
    functions: int
    classes: int
    max_function_lines: int
    bare_excepts: int
    missing_docstrings: int
    sqlite_connects: int


@dataclass
class CritiqueFinding:
    category: str  # "reliability" | "token_efficiency" | "complexity" | "coordination" | "security"
    severity: str  # "high" | "medium" | "low"
    target: str
    summary: str
    recommendation: str
    estimated_token_saving: int = 0


@dataclass
class SelfCritiqueReport:
    generated_at: str
    repo_root: str
    modules_scanned: int
    total_lines: int
    strengths: list[str] = field(default_factory=list)
    findings: list[CritiqueFinding] = field(default_factory=list)
    coordination_ok: bool | None = None
    coordination_detail: str = ""
    efficiency_score: int = 100

    def to_compact_capsule(self, max_chars: int = 1200) -> str:
        """Return an ultra-compact JSON capsule to crush downstream LLM token usage."""
        top_findings = [
            {
                "cat": f.category,
                "sev": f.severity,
                "tgt": Path(f.target).name,
                "msg": f.summary[:90],
            }
            for f in self.findings[:5]
        ]
        payload = {
            "score": self.efficiency_score,
            "mods": self.modules_scanned,
            "loc": self.total_lines,
            "coord_ok": self.coordination_ok,
            "findings_count": len(self.findings),
            "top": top_findings,
        }
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(raw) <= max_chars:
            return raw
        payload["top"] = top_findings[:2]
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))[:max_chars]

    def to_markdown(self) -> str:
        lines = [
            "# Qudron Self-Critique & Evolution Report",
            f"- Generated: `{self.generated_at}`",
            f"- Modules scanned: `{self.modules_scanned}` | Total LOC: `{self.total_lines}`",
            f"- Efficiency Score: **{self.efficiency_score}/100**",
            f"- Coordination Integrity: `{self.coordination_ok}` ({self.coordination_detail})",
            "",
            "## Strengths",
        ]
        for s in self.strengths:
            lines.append(f"- {s}")
        lines.append("")
        lines.append(f"## Critique Findings ({len(self.findings)})")
        for f in self.findings[:20]:
            lines.append(
                f"- **[{f.severity.upper()}] ({f.category})** `{f.target}`: {f.summary} "
                f"-> *Action:* {f.recommendation}"
            )
        return "\n".join(lines) + "\n"


def analyze_python_file(path: Path, repo_root: Path) -> ModuleMetrics:
    """Analyze a single Python file via AST without executing it."""
    source = path.read_text(encoding="utf-8", errors="replace")
    line_count = len(source.splitlines())
    tree = ast.parse(source, filename=str(path))

    functions = 0
    classes = 0
    max_fn_lines = 0
    bare_excepts = 0
    missing_docs = 0
    sqlite_connects = source.count("sqlite3.connect(")

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions += 1
            end_ln = getattr(node, "end_lineno", node.lineno) or node.lineno
            fn_len = max(1, end_ln - node.lineno + 1)
            if fn_len > max_fn_lines:
                max_fn_lines = fn_len
            if not ast.get_docstring(node) and not node.name.startswith("_"):
                missing_docs += 1
        elif isinstance(node, ast.ClassDef):
            classes += 1
            if not ast.get_docstring(node):
                missing_docs += 1
        elif isinstance(node, ast.ExceptHandler):
            if node.type is None:
                bare_excepts += 1

    rel = str(path.relative_to(repo_root)).replace("\\", "/")
    return ModuleMetrics(
        path=rel,
        lines=line_count,
        functions=functions,
        classes=classes,
        max_function_lines=max_fn_lines,
        bare_excepts=bare_excepts,
        missing_docstrings=missing_docs,
        sqlite_connects=sqlite_connects,
    )


def check_coordination_integrity(repo_root: Path) -> tuple[bool | None, str]:
    """Run coord.py verify in read-only mode if present."""
    coord_py = repo_root / ".agent-coordination" / "coord.py"
    if not coord_py.exists():
        return None, "coord.py not found"
    try:
        proc = subprocess.run(
            [sys.executable, str(coord_py), "verify"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        out = (proc.stdout or proc.stderr).strip().splitlines()
        detail = out[-1] if out else f"exit={proc.returncode}"
        return proc.returncode == 0, detail
    except Exception as exc:
        return False, f"verify error: {exc}"


def run_self_critique(repo_root: Path | str) -> SelfCritiqueReport:
    """Scan Qudron runtime modules and produce a deterministic self-critique report."""
    root = Path(repo_root).resolve()
    runtime_dir = root / "ops" / "qudron-runtime"
    report = SelfCritiqueReport(
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        repo_root=str(root),
        modules_scanned=0,
        total_lines=0,
    )

    py_files: list[Path] = []
    if runtime_dir.exists():
        for p in sorted(runtime_dir.glob("*.py")):
            if p.name.startswith("__"):
                continue
            py_files.append(p)

    score = 100
    for py_path in py_files:
        try:
            m = analyze_python_file(py_path, root)
        except SyntaxError as exc:
            report.findings.append(
                CritiqueFinding(
                    category="reliability",
                    severity="high",
                    target=str(py_path.relative_to(root)).replace("\\", "/"),
                    summary=f"SyntaxError at line {exc.lineno}: {exc.msg}",
                    recommendation="Fix syntax error immediately before any release.",
                )
            )
            score -= 20
            continue

        report.modules_scanned += 1
        report.total_lines += m.lines

        if m.bare_excepts > 0:
            report.findings.append(
                CritiqueFinding(
                    category="reliability",
                    severity="medium",
                    target=m.path,
                    summary=f"{m.bare_excepts} bare except clause(s) can hide real failures.",
                    recommendation="Replace bare `except:` with explicit exception types.",
                )
            )
            score -= min(6, m.bare_excepts * 2)

        if m.max_function_lines > 140:
            report.findings.append(
                CritiqueFinding(
                    category="complexity",
                    severity="medium",
                    target=m.path,
                    summary=f"Largest function is {m.max_function_lines} lines (reduces maintainability & increases AI context tokens).",
                    recommendation="Split oversized functions into focused helpers to cut context tokens.",
                    estimated_token_saving=max(100, m.max_function_lines * 3),
                )
            )
            score -= 3

        if m.lines > 900:
            report.findings.append(
                CritiqueFinding(
                    category="token_efficiency",
                    severity="low",
                    target=m.path,
                    summary=f"Large module ({m.lines} LOC) increases agent read/context cost.",
                    recommendation="Extract cohesive submodules or use symbol-level indexing.",
                    estimated_token_saving=max(200, m.lines),
                )
            )
            score -= 2

    coord_ok, coord_detail = check_coordination_integrity(root)
    report.coordination_ok = coord_ok
    report.coordination_detail = coord_detail
    if coord_ok is False:
        report.findings.append(
            CritiqueFinding(
                category="coordination",
                severity="high",
                target=".agent-coordination/coord.py",
                summary=f"Coordination integrity check failed: {coord_detail}",
                recommendation="Inspect hash chain and run coord.py verify.",
            )
        )
        score -= 15

    # Check if BOARD.md is behind HEAD.json
    head_json = root / ".agent-coordination" / "board" / "HEAD.json"
    board_md = root / ".agent-coordination" / "board" / "BOARD.md"
    if head_json.exists() and board_md.exists():
        try:
            head_seq = json.loads(head_json.read_text(encoding="utf-8")).get("seq")
            board_text = board_md.read_text(encoding="utf-8")
            if head_seq is not None and f"(last seq {head_seq})" not in board_text:
                report.findings.append(
                    CritiqueFinding(
                        category="coordination",
                        severity="low",
                        target=".agent-coordination/board/BOARD.md",
                        summary=f"BOARD.md snapshot is behind HEAD.json (seq {head_seq}).",
                        recommendation="Regenerate BOARD.md so all agents read current state.",
                    )
                )
                score -= 2
        except Exception:
            pass

    if report.modules_scanned > 0:
        report.strengths.append(
            f"All {report.modules_scanned} scanned runtime modules parsed cleanly with 0 syntax errors."
        )
    if coord_ok is True:
        report.strengths.append(f"Coordination hash chain verified: {coord_detail}.")

    registry_path = runtime_dir / "agent_registry.json"
    if registry_path.exists():
        try:
            reg = json.loads(registry_path.read_text(encoding="utf-8"))
            report.strengths.append(
                f"Agent registry active with {len(reg.get('agents', []))} roles across {len(reg.get('teams', {}))} teams."
            )
        except Exception:
            pass

    report.efficiency_score = max(0, min(100, score))
    return report


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    repo_root = Path(__file__).resolve().parent.parent.parent
    report = run_self_critique(repo_root)
    if "--capsule" in sys.argv:
        print(report.to_compact_capsule())
    elif "--json" in sys.argv:
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    else:
        print(report.to_markdown())
        print("Compact Capsule:", report.to_compact_capsule())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
