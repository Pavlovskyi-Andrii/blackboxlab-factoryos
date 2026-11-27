"""T-737 Faceless Creator A/B S1 (issue #469): private 9:16 face-switch clip — script timing, honest brief, the
face-switch evidence metric, label detector, camera continuity, deterministic persona drawing, private output guard.

    python test_face_switch.py

No full render here (about two minutes per clip); the end-to-end render and its QA receipt are produced with
`python -m film_studio.face_switch --variant A --out <private dir>`.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from film_studio import face_switch as fs
from film_studio.render import RenderError

ROOT = Path(__file__).resolve().parent


def fonts_available() -> bool:
    try:
        fs._fonts()
        return True
    except Exception:
        return False


class ScriptTest(unittest.TestCase):
    def build(self, variant, tts=None):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(fs, "_tts", tts or (lambda text, out: None)):
            return fs.build_script(variant, Path(tmp))

    def test_scripts_fit_9_16_limits_and_switch_to_another_face(self):
        for variant in fs.VARIANTS:
            script, clips = self.build(variant)
            self.assertEqual(clips, {})
            self.assertTrue(fs.MIN_SEC <= script["duration"] <= fs.MAX_SEC, script["duration"])
            self.assertEqual(script["frames"], round(script["duration"] * fs.FPS))
            self.assertEqual([(s["from"], s["to"]) for s in script["switches"]], [(0, 1), (1, 2)])
            starts = [ln["start"] for ln in script["lines"]]
            self.assertEqual(starts, sorted(starts))
            for a, b in zip(script["lines"], script["lines"][1:]):
                self.assertLessEqual(a["end"], b["start"])                    # lines never overlap
            for sw in script["switches"]:                                     # no line is spoken across a snap
                self.assertFalse(any(ln["start"] < sw["at"] < ln["end"] for ln in script["lines"]))
            self.assertEqual(script["cta"]["title"], "Join early access")
            self.assertEqual(script["voice"], {"engine": "none", "used": False,
                                               "note": "espeak-ng not installed: captions only"})

    def test_line_timing_comes_from_the_real_voice_length(self):
        script, clips = self.build("A", tts=lambda text, out: np.zeros(int(1.5 * fs.SAMPLE_RATE), np.float32))
        self.assertEqual(len(clips), len(script["lines"]))
        self.assertTrue(all(abs(ln["end"] - ln["start"] - 1.5) < 1e-3 for ln in script["lines"]))
        self.assertEqual(script["duration"], fs.MIN_SEC)                   # short speech: the end card holds longer
        self.assertTrue(script["voice"]["used"])
        with self.assertRaises(ValueError):                                   # too much speech for a short clip
            self.build("A", tts=lambda text, out: np.zeros(int(7 * fs.SAMPLE_RATE), np.float32))

    def test_brief_is_honest(self):
        b = fs.brief("A")
        self.assertEqual((b["label"], b["cost_usd"], b["publishing"]), (fs.LABEL, 0, "none (private review)"))
        self.assertIn("18+", b["audience"])
        self.assertIn("no guarantee of anonymity or earnings", b["disclaimer"])
        self.assertIn("no statistical winner", b["comparison_mode"])
        self.assertIn("no real person", b["presenter"])
        for variant in fs.VARIANTS:                                           # no promise of anonymity or income
            text = " ".join(x.get("say", "") for x in fs.VARIANTS[variant]["beats"]).lower()
            for word in ("anonymous", "guarantee", "earn", "money", "income"):
                self.assertNotIn(word, text)


class EvidenceTest(unittest.TestCase):
    def frames(self):
        rng = np.random.default_rng(1)
        base = rng.integers(0, 255, (fs.H, fs.W, 3)).astype(np.uint8)
        return base, base.copy()

    def test_face_change_with_a_still_body_and_room_passes(self):
        before, after = self.frames()
        x0, y0, x1, y1 = fs.FACE_BOX
        after[y0:y1, x0:x1] = 255 - after[y0:y1, x0:x1]
        ev = fs.switch_evidence(before, after)
        self.assertTrue(ev["pass"], ev)
        self.assertEqual(ev["still_max_mean_abs_diff"], 0.0)

    def test_cut_to_another_shot_or_no_change_fails(self):
        before, after = self.frames()
        self.assertFalse(fs.switch_evidence(before, after)["pass"])           # nothing changed
        self.assertFalse(fs.switch_evidence(before, 255 - before)["pass"])    # everything changed: not a face switch
        tiny = before.copy()
        x0, y0, x1, y1 = fs.FACE_BOX
        tiny[y0:y0 + 10, x0:x1] = 0                                           # a few rows only
        self.assertFalse(fs.switch_evidence(before, tiny)["pass"])

    def test_overlays_stay_out_of_the_measured_regions(self):
        for x0, y0, x1, y1 in (fs.FACE_BOX,) + fs.STILL_BOXES:
            self.assertGreater(y0, 210)                                       # label / variant chips end at ~200
            self.assertTrue(y1 <= 1330 or y0 >= 1560)                         # captions sit at 1340..1540

    @unittest.skipUnless(fonts_available(), "DejaVu fonts not installed")
    def test_label_detector(self):
        frame = np.full((fs.H, fs.W, 3), 200, np.uint8)
        self.assertFalse(fs.label_present(frame))
        from PIL import Image
        img = Image.fromarray(frame)
        label = fs.build_overlays({"hook": "h", "lines": [], "switches": [], "cta": None}, "A")["label"]
        img.paste(label, (44, 150), label)
        self.assertTrue(fs.label_present(np.asarray(img)))


class MotionTest(unittest.TestCase):
    def test_camera_is_continuous_except_the_snap(self):
        switches, dur = [9.0, 19.0], 28.0
        for t in (1.0, 5.0, 12.0, 24.0):
            self.assertLess(abs(fs.camera_scale(t + 1, dur, switches) - fs.camera_scale(t, dur, switches)), 0.003)
        self.assertGreater(fs.camera_scale(9.0, dur, switches) - fs.camera_scale(8.5, dur, switches), 0.05)
        self.assertLess(abs(fs.camera_scale(9.0 + fs.AFTER_SEC, dur, switches) - fs.camera_scale(8.7, dur, switches)), 0.003)

    def test_blinks_avoid_the_switch_and_mouth_follows_the_voice(self):
        blinks = fs.blink_track(900, [9.0, 19.0])
        self.assertTrue(any(blinks))
        self.assertFalse(any(blinks[f] for f in range(int(8.5 * fs.FPS), int(9.5 * fs.FPS))))
        voice = np.zeros(fs.SAMPLE_RATE * 2, np.float32)
        voice[fs.SAMPLE_RATE:] = 0.5 * np.sin(np.arange(fs.SAMPLE_RATE) / 7.0)
        mouths = fs.mouth_track(voice, 60)
        self.assertEqual(set(mouths[:30]), {0})
        self.assertGreater(max(mouths[30:]), 1)


class DrawingTest(unittest.TestCase):
    def test_persona_drawing_is_deterministic_and_the_faces_differ(self):
        a = np.asarray(fs.draw_head(fs.FACES[0], 0, 0))
        self.assertTrue(np.array_equal(a, np.asarray(fs.draw_head(fs.FACES[0], 0, 0))))
        b = np.asarray(fs.draw_head(fs.FACES[1], 0, 0))
        self.assertGreater(float(np.mean(np.abs(a.astype(np.float32) - b.astype(np.float32)))), 5)
        self.assertEqual(len({f.name for f in fs.FACES}), len(fs.FACES))


class PrivacyTest(unittest.TestCase):
    def test_render_refuses_an_output_inside_the_repository(self):
        with self.assertRaises(RenderError):
            fs.render("A", ROOT / "static" / "faceless-test")
        self.assertFalse((ROOT / "static" / "faceless-test").exists())


if __name__ == "__main__":
    unittest.main()
