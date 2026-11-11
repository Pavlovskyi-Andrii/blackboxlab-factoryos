"""R-0058 / #289: verification docs may only use the honest status vocabulary.

A row in a docs/verification stage table must say WORKS, PARTIAL, BROKEN, UNKNOWN or NOT STARTED,
so an unobserved stage is never written up as done.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent
ALLOWED = ("WORKS", "PARTIAL", "BROKEN", "UNKNOWN", "NOT STARTED")


def stage_rows(text: str) -> list[list[str]]:
    rows, in_table = [], False
    for line in text.splitlines():
        if line.strip().lower().startswith("| stage |"):
            in_table = True
            continue
        if in_table:
            if not line.startswith("|"):
                break
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells and not re.fullmatch(r"-+", cells[0]):
                rows.append(cells)
    return rows


def check(path: pathlib.Path) -> list[str]:
    problems = []
    rows = stage_rows(path.read_text(encoding="utf-8"))
    if not rows:
        problems.append(f"{path.name}: no stage table")
    for cells in rows:
        if len(cells) < 3 or not cells[1].startswith(ALLOWED):
            problems.append(f"{path.name}: bad status in row {cells[:2]}")
        elif not cells[2]:
            problems.append(f"{path.name}: row {cells[0]!r} has no evidence")
    return problems


def test_stage_rows_parser():
    sample = "| Stage | Status | Evidence |\n|---|---|---|\n| push | DONE | x |\n| pr | UNKNOWN | y |\n"
    assert stage_rows(sample) == [["push", "DONE", "x"], ["pr", "UNKNOWN", "y"]]


def test_verification_docs():
    docs = sorted((ROOT / "docs" / "verification").glob("*.md"))
    assert docs, "docs/verification is empty"
    problems = [p for d in docs for p in check(d)]
    assert not problems, problems


if __name__ == "__main__":
    test_stage_rows_parser()
    test_verification_docs()
    print("verification docs: OK")
