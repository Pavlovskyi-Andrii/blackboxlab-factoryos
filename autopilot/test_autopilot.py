import tempfile
from pathlib import Path

from autopilot import autopilot as ap


def write_roadmap(text: str) -> Path:
    root = Path(tempfile.mkdtemp(prefix="factoryos-autopilot-test-"))
    path = root / "ROADMAP.md"
    path.write_text(text, encoding="utf-8")
    return path


def main():
    path = write_roadmap(
        """# Roadmap

## v5
- [x] T-001 Finished
- [ ] [HUMAN] T-002 Owner credential
- [ ] T-003 Safe next task
- [ ] T-004 Later safe task
"""
    )
    tasks = ap.parse_roadmap(path)
    assert [x["id"] for x in tasks] == ["T-001", "T-002", "T-003", "T-004"]
    assert ap.next_safe_task(path)["id"] == "T-003"
    assert ap.first_human_blocker(path).startswith("T-002")
    assert ap.roadmap_has_safe_work(path) is True

    expected = ap.next_safe_task(path)
    assert ap.done_status_is_consistent({"task": "T-003", "status": "done"}, expected, path) is False

    path.write_text(
        path.read_text(encoding="utf-8").replace("- [ ] T-003", "- [x] T-003"),
        encoding="utf-8",
    )
    assert ap.done_status_is_consistent({"task": "T-003", "status": "done"}, expected, path) is True
    assert ap.next_safe_task(path)["id"] == "T-004"

    path.write_text(
        path.read_text(encoding="utf-8").replace("- [ ] T-004", "- [x] T-004"),
        encoding="utf-8",
    )
    assert ap.next_safe_task(path) is None
    assert ap.roadmap_has_safe_work(path) is False
    assert ap.first_human_blocker(path).startswith("T-002")
    assert "T-002" in ap.idle_notice(path)

    no_human = write_roadmap("# Roadmap\n\n## v5\n- [x] T-001 Finished\n")
    assert ap.idle_notice(no_human).startswith("🏁")
    dependency_and_owner_regression()
    print("Autopilot roadmap advancement tests passed")


def dependency_and_owner_regression():
    # T-537: unmet Depends are skipped, unrelated safe work advances, completion unlocks, HUMAN never runs.
    path = write_roadmap(
        """# Roadmap

## v5
- [ ] T-010 Foundation
  Owner: ChatGPT
- [ ] T-011 Needs foundation
  Depends: T-010
- [ ] [HUMAN] T-012 Owner credential
- [ ] T-013 Needs human task
  Depends: T-012
- [ ] T-014 Needs unknown task
  Depends: T-999, not-a-task
- [ ] T-015 Unrelated safe task
  Owner: any
- [ ] T-016 Claude lane task
  Owner: claude
"""
    )
    tasks = ap.parse_roadmap(path)
    by_id = {x["id"]: x for x in tasks}
    assert by_id["T-011"]["depends"] == ["T-010"]
    assert by_id["T-014"]["depends"] == ["T-999"]
    assert by_id["T-010"]["owner"] == "chatgpt"
    # ChatGPT-owned work is never taken by the Claude runner; dependents wait for it.
    assert ap.next_safe_task(path, "claude")["id"] == "T-015"
    assert ap.next_safe_task(path, "chatgpt")["id"] == "T-010"
    assert ap.unmet_dependencies(by_id["T-014"], tasks) == ["T-999"]

    text = path.read_text(encoding="utf-8").replace("- [ ] T-015", "- [x] T-015")
    path.write_text(text, encoding="utf-8")
    assert ap.next_safe_task(path, "claude")["id"] == "T-016"

    text = text.replace("- [ ] T-016", "- [x] T-016")
    path.write_text(text, encoding="utf-8")
    assert ap.next_safe_task(path, "claude") is None
    assert "T-011" in ap.idle_notice(path)

    # Completed dependency unlocks the dependent task.
    text = text.replace("- [ ] T-010", "- [x] T-010")
    path.write_text(text, encoding="utf-8")
    assert ap.next_safe_task(path, "claude")["id"] == "T-011"

    # A HUMAN task is never selectable, even when it is the only open dependency path.
    text = text.replace("- [ ] T-011", "- [x] T-011")
    path.write_text(text, encoding="utf-8")
    assert ap.next_safe_task(path, "claude") is None
    for operator in ("claude", "chatgpt", "gemini"):
        selected = ap.next_safe_task(path, operator)
        assert selected is None or not selected["human"]
    text = text.replace("- [ ] [HUMAN] T-012", "- [x] [HUMAN] T-012")
    path.write_text(text, encoding="utf-8")
    assert ap.next_safe_task(path, "claude")["id"] == "T-013"

    # Inline metadata as written in the live ROADMAP: other fields on the same line, trailing punctuation.
    inline = write_roadmap(
        """# Roadmap

## P0
- [ ] T-020 Takeover
  Planner: owner; Executor: Claude Code Pro. P0.
- [ ] T-021 Live acceptance
  Planner: owner; Executor: Claude Code Pro. P0. Depends: T-020.
- [ ] T-022 Hotfix
  Owner: ChatGPT. Depends: T-020 (implementation merged in #63; acceptance remains T-021).
"""
    )
    by_id = {x["id"]: x for x in ap.parse_roadmap(inline)}
    assert by_id["T-020"]["owner"] == "" and by_id["T-020"]["depends"] == []
    assert by_id["T-021"]["depends"] == ["T-020"]
    assert by_id["T-022"]["owner"] == "chatgpt"
    assert by_id["T-022"]["depends"] == ["T-020"]
    assert ap.next_safe_task(inline, "claude")["id"] == "T-020"
    text = text.replace("- [ ] T-013", "- [x] T-013")
    path.write_text(text, encoding="utf-8")
    assert ap.next_safe_task(path, "claude") is None  # T-014 waits forever on unknown T-999
    assert "T-014" in ap.idle_notice(path)
    print("Autopilot dependency/owner scheduler tests passed")


if __name__ == "__main__":
    main()
