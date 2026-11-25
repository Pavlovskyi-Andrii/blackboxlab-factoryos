"""Deterministic unit tests for measured MyCast chapters; no external services."""
import unittest

from mycast_chapter_index import MeasuredSection, format_ukrainian_chapters, timestamp, validate_chapters


class ChapterIndexTests(unittest.TestCase):
    def test_measured_offsets_and_ukrainian(self):
        sections = [MeasuredSection("Головне", 0, 5000), MeasuredSection("Новини ШІ", 5200, 12500)]
        self.assertEqual(format_ukrainian_chapters(sections, 13000), "00:00 — Головне\n00:05 — Новини ШІ")
        self.assertEqual(validate_chapters(sections, 13000)[1]["end_ms"], 12500)

    def test_five_sections(self):
        sections = [MeasuredSection(str(i), i * 1000) for i in range(5)]
        self.assertEqual(len(validate_chapters(sections, 5000)), 5)

    def test_invalid_offsets_rejected(self):
        invalid = [
            ([MeasuredSection("A", -1)], 1000),
            ([MeasuredSection("A", 1000)], 1000),
            ([MeasuredSection("A", 0, 1100)], 1000),
            ([MeasuredSection("A", 0, 600), MeasuredSection("B", 500)], 1000),
            ([MeasuredSection("A", 0), MeasuredSection("B", 0)], 1000),
            ([MeasuredSection("A", True)], 1000),
            ([MeasuredSection("", 0)], 1000),
        ]
        for sections, duration in invalid:
            with self.subTest(sections=sections):
                with self.assertRaises(ValueError):
                    validate_chapters(sections, duration)

    def test_no_duration_or_guessed_timestamp(self):
        with self.assertRaises(ValueError):
            validate_chapters([MeasuredSection("A", 0)], 0)
        with self.assertRaises(ValueError):
            timestamp(-1)
        self.assertEqual(timestamp(3600000), "01:00:00")


if __name__ == "__main__":
    unittest.main()
