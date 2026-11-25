"""T-729: ROADMAP.md on this branch has one line per task number and no Depends: on an unknown task.

Two sessions once gave new work numbers that were already taken on main (T-726/T-727, 2026-11-23). This test makes
the merge that would create a duplicate number fail in CI instead of silently mixing two tasks.
"""
import pathlib
import unittest

import coordination as co

ROOT = pathlib.Path(__file__).resolve().parent


class RoadmapIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
        self.report = co.build_report(self.text, [], [], [])

    def test_every_task_number_is_unique(self):
        dups = [f for f in self.report["findings"] if f["code"] == "duplicate_task_id"]
        self.assertEqual(dups, [], "duplicate ROADMAP task numbers: " +
                         "; ".join(f"{f['task_ids'][0]} on lines {f['lines']}" for f in dups) +
                         f". Use the next free number ({co.next_free_id(self.report)}).")

    def test_open_tasks_depend_only_on_known_tasks(self):
        bad = [f for f in self.report["findings"] if f["code"] == "unknown_dependency"]
        self.assertEqual(bad, [], "Depends: names an unknown task: " +
                         "; ".join(f"{f['task_ids'][0]} -> {f['depends']}" for f in bad))

    def test_parser_sees_every_task_line(self):
        lines = [ln for ln in self.text.splitlines() if ln.startswith("- [") and " T-" in ln[:20]]
        self.assertEqual(len(co.parse_roadmap(self.text)), len(lines))


if __name__ == "__main__":
    unittest.main(verbosity=1)
