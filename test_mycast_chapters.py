"""MyCast chapter timecodes (owner 2026-11-27): python test_mycast_chapters.py"""
from mycast_chapters import caption_block, chunk_line_starts, clean_chapters, clock

LINES = [["A", "Привіт"], ["B", "Перша новина " * 10], ["A", "Так"], ["B", "Друга новина " * 20], ["A", "Бувайте"]]


def test_clean_chapters():
    ep = {"lines": LINES, "chapters": [{"line": 1, "title": "  Вступ  "}, {"line": 3, "title": "OpenAI"}]}
    assert clean_chapters(ep) == [{"line": 0, "title": "Вступ"}, {"line": 3, "title": "OpenAI"}]  # first is pinned to 0:00
    bad = [{"line": 9, "title": "outside"}, {"line": True, "title": "bool"}, {"line": "2", "title": "str"},
           {"line": 2, "title": ""}, "text", {"line": 1}]
    assert clean_chapters({"lines": LINES, "chapters": bad + [{"line": 0, "title": "A"}, {"line": 0, "title": "same"},
                                                              {"line": 2, "title": "B"}]}) == [{"line": 0, "title": "A"}, {"line": 2, "title": "B"}]
    assert clean_chapters({"lines": LINES, "chapters": [{"line": 0, "title": "only one"}]}) == []
    assert clean_chapters({"lines": LINES}) == [] and clean_chapters({"chapters": []}) == [] and clean_chapters(None) == []
    long = clean_chapters({"lines": LINES, "chapters": [{"line": 0, "title": "x" * 80}, {"line": 1, "title": "y\nz"}]})
    assert len(long[0]["title"]) == 48 and long[0]["title"].endswith("…") and long[1]["title"] == "y z"
    many = clean_chapters({"lines": [["A", "x"]] * 30, "chapters": [{"line": n, "title": str(n)} for n in range(30)]})
    assert len(many) == 12


def test_chunk_line_starts():
    chunks = [[("A", "aaaa"), ("B", "bbbbbbbbbbbb")], [("A", "cc")]]
    starts = chunk_line_starts(chunks, [16.0, 4.0], 0.5)
    assert starts == [0.0, 4.0, 16.5]
    assert chunk_line_starts([], [], 0.5) == []


def test_clock_and_caption():
    assert [clock(s) for s in (0, 59.4, 59.6, 61, 3599, 3725)] == ["0:00", "0:59", "1:00", "1:01", "59:59", "1:02:05"]
    ep = {"lines": LINES, "chapters": [{"line": 0, "title": "Вступ"}, {"line": 3, "title": "Друга новина"}]}
    assert caption_block(ep, [0, 2, 40, 72.4, 150]) == "0:00 Вступ\n1:12 Друга новина"
    assert caption_block(ep, [0, 2]) == ""  # timing that does not match the script is never shown
    assert caption_block({"lines": LINES}, [0, 2, 40, 72.4, 150]) == ""


if __name__ == "__main__":
    test_clean_chapters()
    test_chunk_line_starts()
    test_clock_and_caption()
    print("MyCast chapter tests passed")
