"""Tier-1 gate: offline, < 60 s, zero paid calls. Run: `uv run scripts/verify.py`."""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUDGET_S = 60.0
STATE_MAX_LINES = 40
DOC_GLOBS = ["README.md", "AGENTS.md", "docs/**/*.md", "evals/**/*.md", ".agents/**/*.md"]
_RUN_ID = re.compile(r"\b(D\d-[A-Z0-9]+(?:-[A-Z0-9]+)*-\d{2})\b")
_LINK = re.compile(r"\]\((?!https?://|mailto:|#)([^)\s]+)\)")


def run(name: str, cmd: list[str]) -> bool:
    t = time.perf_counter()
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    ok = proc.returncode == 0
    print(f"[{'PASS' if ok else 'FAIL'}] {name} ({time.perf_counter() - t:.1f}s)")
    if not ok:
        print((proc.stdout + proc.stderr)[-4000:])
    return ok


def docs_check() -> bool:
    """Forbidden claims, dead relative links, STATE.md size."""
    problems: list[str] = []
    terms_file = ROOT / "scripts" / "forbidden_terms.txt"
    terms = [
        t.strip().lower()
        for t in terms_file.read_text(encoding="utf-8").splitlines()
        if t.strip() and not t.startswith("#")
    ]
    files = sorted({p for g in DOC_GLOBS for p in ROOT.glob(g) if p.is_file()})
    for f in files:
        text = f.read_text(encoding="utf-8")
        low = text.lower()
        for term in terms:
            if term in low:
                problems.append(f"{f.relative_to(ROOT)}: forbidden term '{term}'")
        for target in _LINK.findall(text):
            path = target.split("#", 1)[0]
            if path and not (f.parent / path).exists():
                problems.append(f"{f.relative_to(ROOT)}: dead link {target}")
    # Every run id cited in the README must exist in FINDINGS (numbers shown must be backed by a results row).
    findings = (ROOT / "evals" / "FINDINGS.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for run_id in sorted(set(_RUN_ID.findall(readme))):
        if f"| {run_id} |" not in findings:
            problems.append(f"README.md: run id {run_id} not found in evals/FINDINGS.md")
    state = ROOT / "docs" / "STATE.md"
    if state.exists() and len(state.read_text(encoding="utf-8").splitlines()) > STATE_MAX_LINES:
        problems.append(f"docs/STATE.md exceeds {STATE_MAX_LINES} lines")
    ok = not problems
    print(f"[{'PASS' if ok else 'FAIL'}] docs consistency ({len(files)} files)")
    for p in problems:
        print(f"  - {p}")
    return ok


def main() -> int:
    start = time.perf_counter()
    py = [sys.executable, "-m"]
    results = [
        run("ruff", [*py, "ruff", "check", "src", "tests", "scripts"]),
        run(
            "mypy --strict (src)",
            [*py, "mypy", "src", "--cache-dir", str(Path(tempfile.gettempdir()) / "lexgrid-mypy")],
        ),
        run("pytest (offline)", [*py, "pytest", "-q", "-p", "no:cacheprovider"]),
        run("source registry", [*py, "lexgrid.cli", "sources", "check"]),
        docs_check(),
    ]
    elapsed = time.perf_counter() - start
    in_budget = elapsed < BUDGET_S
    print(f"[{'PASS' if in_budget else 'FAIL'}] time budget {elapsed:.1f}s < {BUDGET_S:.0f}s")
    ok = all(results) and in_budget
    print("VERIFY GREEN" if ok else "VERIFY RED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
