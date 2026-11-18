---
name: handover
description: End-of-session handover. Updates docs/STATE.md (≤ 40 lines) and docs/PROJECT_HANDOVER.md with verified facts only, so the next session can resume cold.
---

# handover

1. Run `uv run scripts/verify.py`; copy the exact pass/fail lines and test count.
2. Update `docs/STATE.md`: current day/milestone, next 3 actions, blockers, last 3 decisions,
   verified numbers (each with a link to its FINDINGS row). Keep it ≤ 40 lines.
3. Update `docs/PROJECT_HANDOVER.md`: what exists, how to run it, trust boundaries, eval results, backlog links.
4. Never write a number that is not in `evals/FINDINGS.md` or the verify output of this session.
5. List uncommitted changes (`git status --short`) and ask before committing.
