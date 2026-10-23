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
    print("Autopilot roadmap advancement tests passed")


if __name__ == "__main__":
    main()
