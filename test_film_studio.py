"""T-730 AI Film Studio S1: contracts, rights gate, deterministic plan, inert text, offline renderer, QA receipt.

    python test_film_studio.py

The end-to-end render test needs ffmpeg, ffprobe and DejaVu fonts; without them it is skipped (and says so).
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from film_studio import plan as fplan
from film_studio import narration, procedural, qa, render
from film_studio.plan import PlanError, RightsBlocked, build_plan
from film_studio.schema import (ValidationError, manifest_from_candidates, validate_asset_manifest,
                                validate_film_bible, validate_storyboard)

ROOT = Path(__file__).resolve().parent
PACK = ROOT / "docs/storyboards/blackbox-lab-45s"


def load(name):
    return json.loads((PACK / name).read_text(encoding="utf-8"))


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verified_asset(aid, path, data=b"img", **extra):
    a = {"id": aid, "source_type": "licensed_stock", "provider": "Example", "url": "https://example.org/p/1",
         "author": "A. Photographer", "licence": {"name": "Example Licence", "url": "https://example.org/licence"},
         "attribution": "Photo: A. Photographer", "rights_status": "verified", "verified_at": "2026-11-23T00:00:00Z",
         "verified_by": "test", "sha256": sha(data), "local_path": path}
    a.update(extra)
    return a


class Fixture(unittest.TestCase):
    def setUp(self):
        self.sb, self.bible, self.cand = load("storyboard.json"), load("film_bible.json"), load("asset_candidates.json")
        self.tmp = Path(tempfile.mkdtemp(prefix="film-studio-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def verified_manifest(self):
        """Every storyboard asset id, verified, with a real file whose sha256 matches."""
        assets = []
        for s in self.sb["shots"]:
            data = f"pixels-{s['asset_id']}".encode()
            (self.tmp / f"{s['asset_id']}.png").write_bytes(data)
            assets.append(verified_asset(s["asset_id"], f"{s['asset_id']}.png", data))
        return {"schema": "film-studio/asset-manifest/v1", "project_id": self.sb["project_id"], "assets": assets}


class ContractTest(Fixture):
    def test_shotpack_contracts_validate(self):
        validate_film_bible(self.bible)
        validate_storyboard(self.sb, self.bible)
        m = manifest_from_candidates(self.cand)
        self.assertEqual(len(m["assets"]), 7)
        self.assertTrue(all(a["rights_status"] == "candidate_unverified" for a in m["assets"]))

    def assertInvalid(self, fn, doc, needle, *args):
        with self.assertRaises(ValidationError) as cm:
            fn(doc, *args)
        self.assertIn(needle, str(cm.exception))

    def test_storyboard_rejects_malformed(self):
        cases = []
        d = copy.deepcopy(self.sb); d["shots"][2]["prompt"] = "x"; cases.append((d, "unknown keys"))
        d = copy.deepcopy(self.sb); d["shots"][1]["start_sec"] = 6; d["shots"][1]["end_sec"] = 12
        cases.append((d, "gap/overlap"))
        d = copy.deepcopy(self.sb); d["shots"][6]["duration_sec"] = 8; d["shots"][6]["end_sec"] = 44
        cases.append((d, "sum to 44s"))
        d = copy.deepcopy(self.sb); d["shots"][3]["shot_id"] = "s01"; cases.append((d, "duplicate"))
        d = copy.deepcopy(self.sb); d["shots"][0]["camera"]["preset"] = "crash_zoom"; cases.append((d, "preset"))
        d = copy.deepcopy(self.sb); d["shots"][0]["camera"]["zoom_max"] = 1.2; cases.append((d, "max_zoom"))
        d = copy.deepcopy(self.sb); d["schema"] = "film-studio/storyboard/v0"; cases.append((d, "schema"))
        d = copy.deepcopy(self.sb); d["shots"][0]["voiceover_ru"] = "a\x00b"; cases.append((d, "control"))
        d = copy.deepcopy(self.sb); d["shots"][0]["duration_sec"] = 5.01; d["shots"][0]["end_sec"] = 5.01
        cases.append((d, "whole number of frames"))
        d = copy.deepcopy(self.sb); d["format"]["width"] = 1000; cases.append((d, "is not 16:9"))
        d = copy.deepcopy(self.sb); d["shots"] = []; cases.append((d, "1..24"))
        for doc, needle in cases:
            with self.subTest(needle=needle):
                self.assertInvalid(validate_storyboard, doc, needle, self.bible)

    def test_shot_durations_sum_exactly(self):
        total = sum(s["duration_sec"] for s in self.sb["shots"])
        self.assertEqual(total, 45)
        self.assertEqual(self.sb["format"]["seconds"], 45)

    def test_bible_must_stay_private_and_reviewed(self):
        d = copy.deepcopy(self.bible); d["output"]["private_only"] = False
        self.assertInvalid(validate_film_bible, d, "private_only")
        d = copy.deepcopy(self.bible); del d["truth_policy"]
        self.assertInvalid(validate_film_bible, d, "truth_policy")

    def test_manifest_rejects_incomplete_or_unsafe_assets(self):
        base = {"schema": "film-studio/asset-manifest/v1", "project_id": "p1"}
        ok = verified_asset("a1", "a1.png")
        validate_asset_manifest(dict(base, assets=[ok]))
        cases = [
            ([dict(ok, author=None)], "requires author"),
            ([{k: v for k, v in ok.items() if k != "licence"}], "requires licence"),
            ([dict(ok, sha256="abc")], "64 lowercase hex"),
            ([ok, dict(ok)], "duplicate"),
            ([dict(ok, local_path="../secret.png")], "relative path"),
            ([dict(ok, local_path="/etc/passwd")], "relative path"),
            ([dict(ok, url="http://example.org/x")], "https://"),
            ([dict(ok, url="repo://film_studio/x")], "repo://"),
            ([dict(ok, rights_status="probably_fine")], "rights_status"),
            ([dict(ok, extra="x")], "unknown keys"),
        ]
        for assets, needle in cases:
            with self.subTest(needle=needle):
                self.assertInvalid(validate_asset_manifest, dict(base, assets=assets), needle)


class RightsGateTest(Fixture):
    def test_candidates_block_every_shot(self):
        m = manifest_from_candidates(self.cand)
        with self.assertRaises(RightsBlocked) as cm:
            build_plan(self.sb, self.bible, m, manifest_dir=PACK)
        self.assertEqual([b["shot_id"] for b in cm.exception.blocked], [s["shot_id"] for s in self.sb["shots"]])
        self.assertIn("candidate_unverified", cm.exception.blocked[0]["reason"])

    def test_verified_manifest_plans(self):
        p = build_plan(self.sb, self.bible, self.verified_manifest(), manifest_dir=self.tmp)
        self.assertEqual(p["total_frames"], 45 * 24)

    def test_each_failure_blocks_only_that_shot(self):
        m = self.verified_manifest()
        m["assets"][0]["rights_status"] = "unknown"
        (self.tmp / m["assets"][1]["local_path"]).write_bytes(b"swapped")
        (self.tmp / m["assets"][2]["local_path"]).unlink()
        m["assets"] = [a for a in m["assets"] if a["id"] != self.sb["shots"][3]["asset_id"]]
        with self.assertRaises(RightsBlocked) as cm:
            build_plan(self.sb, self.bible, m, manifest_dir=self.tmp)
        reasons = {b["shot_id"]: b["reason"] for b in cm.exception.blocked}
        self.assertEqual(sorted(reasons), ["s01", "s02", "s03", "s04"])
        self.assertIn("'unknown'", reasons["s01"])
        self.assertIn("sha256 mismatch", reasons["s02"])
        self.assertIn("missing", reasons["s03"])
        self.assertIn("not in manifest", reasons["s04"])

    def test_generative_cinema_needs_approval(self):
        sb = copy.deepcopy(self.sb); sb["shots"][4]["renderer"] = "generative_cinema"
        with self.assertRaises(RightsBlocked) as cm:
            build_plan(sb, self.bible, self.verified_manifest(), manifest_dir=self.tmp)
        self.assertIn("owner approval", cm.exception.blocked[0]["reason"])

    def test_hybrid_falls_back_visibly(self):
        sb = copy.deepcopy(self.sb); sb["shots"][4]["renderer"] = "hybrid_film"
        p = build_plan(sb, self.bible, self.verified_manifest(), manifest_dir=self.tmp)
        self.assertEqual(p["shots"][4]["renderer"], "photo_cinema")
        self.assertIn("unavailable", p["shots"][4]["fallback"])


class PlanTest(Fixture):
    def plan(self, **kw):
        return build_plan(self.sb, self.bible, self.verified_manifest(), manifest_dir=self.tmp, **kw)

    def test_frames_tile_the_film(self):
        p = self.plan()
        self.assertEqual(p["duration_sec"], "45.000")
        self.assertEqual((p["width"], p["height"], p["fps"]), (1920, 1080, 24))
        cursor = 0
        for s in p["shots"]:
            self.assertEqual(s["start_frame"], cursor)
            cursor += s["frames"]
        self.assertEqual(cursor, 1080)
        self.assertEqual(p["shots"][0]["transition_in"], {"type": "fade_from_black", "frames": 10, "source": "storyboard"})
        for prev, cur in zip(p["shots"], p["shots"][1:]):
            self.assertEqual(cur["transition_in"]["type"], "crossfade")
            self.assertEqual(prev["tail_frames"], cur["transition_in"]["frames"])
        self.assertEqual(p["shots"][-1]["tail_frames"], 0)

    def test_plan_is_deterministic_and_cache_keys_are_per_shot(self):
        a, b = self.plan(), self.plan()
        self.assertEqual(a["plan_sha256"], b["plan_sha256"])
        sb = copy.deepcopy(self.sb); sb["shots"][2]["graphics"]["title"] = "НОВЫЙ"
        c = build_plan(sb, self.bible, self.verified_manifest(), manifest_dir=self.tmp)
        changed = [x["shot_id"] for x, y in zip(a["shots"], c["shots"]) if x["cache_key"] != y["cache_key"]]
        self.assertEqual(changed, ["s03"])

    def test_cuts_and_proxy(self):
        p = self.plan(crossfade_sec=0, size=(1280, 720))
        self.assertEqual((p["width"], p["height"]), (1280, 720))
        self.assertTrue(all(s["transition_in"]["type"] == "cut" for s in p["shots"][1:]))
        with self.assertRaises(PlanError):
            self.plan(size=(1280, 700))
        with self.assertRaises(PlanError):
            self.plan(overrides={"s99": "x"})


class CommandTest(Fixture):
    INJECTION = "'; [v]drawtext=text=pwned:fontfile=/etc/passwd,movie=/etc/shadow[x]; %{pts} \\ :"

    def test_text_is_inert_and_commands_deterministic(self):
        sb = copy.deepcopy(self.sb)
        sb["shots"][0]["voiceover_ru"] = self.INJECTION
        sb["shots"][0]["graphics"]["title"] = "T'; movie=/etc/x"
        p = build_plan(sb, self.bible, self.verified_manifest(), manifest_dir=self.tmp)
        fonts = {"regular": "/fonts/R.ttf", "bold": "/fonts/B.ttf"}
        shot = p["shots"][0]
        argv1 = render.shot_command(p, shot, manifest_dir=self.tmp, work=self.tmp / "w", out_clip=Path("c.mp4"),
                                    fonts=fonts)
        argv2 = render.shot_command(p, shot, manifest_dir=self.tmp, work=self.tmp / "w", out_clip=Path("c.mp4"),
                                    fonts=fonts)
        self.assertEqual(argv1, argv2)
        graph = argv1[argv1.index("-filter_complex") + 1]
        for bad in ("pwned", "/etc/", "%{pts}", "movie="):
            self.assertNotIn(bad, graph)
        self.assertIn("expansion=none", graph)
        cap = (self.tmp / "w" / "text" / "s01.caption.txt").read_text(encoding="utf-8")
        self.assertIn("pwned", cap)
        self.assertNotIn("http", " ".join(argv1))

    def test_camera_presets(self):
        for preset in fplan.validate_film_bible(self.bible)["camera_bible"]["moves"]:
            e = render.camera_expressions(preset, 1.08, 120)
            self.assertEqual(set(e), {"z", "x", "y"})
        with self.assertRaises(render.RenderError):
            render.camera_expressions("crash_zoom", 1.08, 10)

    def test_assembly_keeps_exact_length(self):
        p = build_plan(self.sb, self.bible, self.verified_manifest(), manifest_dir=self.tmp)
        argv = render.assemble_command(p, [Path(f"{s['shot_id']}.mp4") for s in p["shots"]], Path("film.mp4"))
        self.assertEqual(argv[argv.index("-frames:v") + 1], "1080")
        graph = argv[argv.index("-filter_complex") + 1]
        self.assertEqual(graph.count("xfade="), 6)
        self.assertIn("offset=5.000000", graph)
        self.assertIn("offset=36.000000", graph)

    def test_output_must_stay_private(self):
        for bad in (ROOT / "static/film", ROOT / "film_studio/out", ROOT):
            with self.assertRaises(render.RenderError):
                render.guard_private_output(bad)
        render.guard_private_output(ROOT / "data/film-studio")
        render.guard_private_output(self.tmp)


class OfflineTest(Fixture):
    def test_no_network_during_generation_planning_and_blocked_cli(self):
        def refuse(*a, **k):
            raise AssertionError("network access attempted")
        with mock.patch.object(socket.socket, "connect", refuse), \
                mock.patch.object(socket, "create_connection", refuse), \
                mock.patch.object(socket, "getaddrinfo", refuse):
            shots = procedural.shots_from_shotpack(self.sb, self.cand)[:1]
            m = procedural.generate(self.tmp / "assets", shots, self.sb["project_id"], generated_at="2026-11-23T00:00:00Z")
            self.assertEqual(m["assets"][0]["rights_status"], "verified")
            out = self.tmp / "blocked"
            with mock.patch("sys.stdout"):
                code = render.main(["--out", str(out)])
            self.assertEqual(code, 3)
            receipt = json.loads((out / "qa_receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "BLOCKED")
            self.assertEqual(receipt["cost"]["usd"], 0.0)
            self.assertIsNone(receipt["film"])

    def test_procedural_stills_are_deterministic(self):
        shots = procedural.shots_from_shotpack(self.sb, self.cand)[6:7]
        a = procedural.generate(self.tmp / "a", shots, "p1", generated_at="2026-11-23T00:00:00Z")
        b = procedural.generate(self.tmp / "b", shots, "p1", generated_at="2026-11-23T00:00:00Z")
        self.assertEqual(a, b)
        self.assertTrue(a["assets"][0]["url"].startswith("repo://"))
        self.assertEqual(a["assets"][0]["substitutes_for"], "pexels-8344064")


def write_tone(path: Path, seconds: float, freq: float = 220.0, rate: int = 22050) -> None:
    """A short mono sine WAV, standing in for a narration line (no TTS needed in tests)."""
    import math
    import struct
    import wave
    n = int(seconds * rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * freq * i / rate))) for i in range(n)))


def narration_doc(directory: Path, project_id: str, lines: dict, **voice) -> Path:
    """Write WAV lines {shot_id: seconds} and a narration.json that names them with their sha256."""
    doc_lines = {}
    for sid, secs in lines.items():
        wav = directory / f"{sid}.wav"
        write_tone(wav, secs)
        doc_lines[sid] = {"path": wav.name, "sha256": hashlib.sha256(wav.read_bytes()).hexdigest()}
    v = {"source": "piper", "model": "ru_RU-test-medium", "model_sha256": "a" * 64, "dataset_licence": "CC0",
         "model_url": "https://example.org/voice"}
    v.update(voice)
    target = directory / "narration.json"
    target.write_text(json.dumps({"schema": narration.SCHEMA_NARRATION, "project_id": project_id, "voice": v,
                                  "lines": doc_lines}), encoding="utf-8")
    return target


class NarrationTest(Fixture):
    """T-735 (S2): one WAV line per shot, placed at its shot, sha256-pinned, never running into the next shot."""

    def plan(self):
        return build_plan(self.sb, self.bible, self.verified_manifest(), manifest_dir=self.tmp, size=(320, 180))

    def test_lines_are_placed_at_their_shots(self):
        p = self.plan()
        doc = narration.load(narration_doc(self.tmp, self.sb["project_id"], {"s01": 2.0, "s03": 1.5}), p)
        starts = {x["shot_id"]: x["start_sec"] for x in doc["lines"]}
        self.assertEqual(starts, {"s01": narration.LEAD_SEC, "s03": 11 + narration.LEAD_SEC})
        argv = render.assemble_command(p, [self.tmp / f"c{i}.mp4" for i in range(len(p["shots"]))],
                                       self.tmp / "f.mp4", doc["lines"])
        graph = argv[argv.index("-filter_complex") + 1]
        self.assertIn("adelay=250|250", graph)
        self.assertIn("adelay=11250|11250", graph)
        self.assertIn("loudnorm=I=-16.0:TP=-1.5", graph)
        self.assertEqual(argv[argv.index("[vout]") + 2], "[aout]")
        silent = render.assemble_command(p, [self.tmp / f"c{i}.mp4" for i in range(len(p["shots"]))], self.tmp / "f.mp4")
        self.assertNotIn("loudnorm", " ".join(silent))

    def test_bad_narration_is_refused(self):
        p = self.plan()
        cases = [
            ({"s01": 4.6}, {}, "does not fit"),                    # s01 is 5 s: 0.25 lead + 0.2 gap leave 4.55 s
            ({"s99": 1.0}, {}, "unknown shot"),
            ({"s01": 1.0}, {"source": "tts_cloud"}, "voice.source"),
            ({"s01": 1.0}, {"model_sha256": ""}, "voice.model_sha256"),
            ({"s01": 1.0}, {"source": "owner_recording"}, "consent"),
            ({"s01": 1.0}, {"source": "voice_clone", "consent": "owner 2026-11-27"}, "voice.model_licence"),
            ({"s01": 1.0}, {"source": "voice_clone", "model_licence": "CPML", "reference_sha256": "b" * 64}, "voice.consent"),
        ]
        for lines, voice, needle in cases:
            with self.subTest(needle=needle):
                d = self.tmp / needle.replace(" ", "_").replace(".", "_")
                d.mkdir()
                with self.assertRaises(ValidationError) as ctx:
                    narration.load(narration_doc(d, self.sb["project_id"], lines, **voice), p)
                self.assertIn(needle, str(ctx.exception))

    def test_cloned_voice_records_model_licence_and_consent(self):
        p = self.plan()
        doc = narration.load(narration_doc(self.tmp, self.sb["project_id"], {"s02": 1.0}, source="voice_clone",
                                           model="xtts_v2", model_licence="CPML (non-commercial)",
                                           reference_sha256="c" * 64, consent="owner sent the sample for this film"), p)
        self.assertEqual(doc["voice"]["source"], "voice_clone")
        self.assertEqual(doc["voice"]["model_licence"], "CPML (non-commercial)")

    def test_changed_wav_is_refused(self):
        p = self.plan()
        target = narration_doc(self.tmp, self.sb["project_id"], {"s02": 1.0})
        write_tone(self.tmp / "s02.wav", 1.0, freq=330.0)        # someone swapped the approved line
        with self.assertRaises(ValidationError) as ctx:
            narration.load(target, p)
        self.assertIn("sha256 mismatch", str(ctx.exception))

    def test_owner_asset_substitutes_a_storyboard_shot(self):
        m = self.verified_manifest()
        last = self.sb["shots"][-1]
        data = b"owner-portrait"
        (self.tmp / "owner.png").write_bytes(data)
        m["assets"].append(verified_asset("owner-s07-portrait", "owner.png", data, source_type="owner_supplied",
                                          url="owner://uploads/portrait", substitutes_for=last["asset_id"],
                                          licence={"name": "Owner-supplied", "url": "owner://consent/1"}))
        mpath = self.tmp / "asset_manifest.json"
        mpath.write_text(json.dumps(m), encoding="utf-8")
        out = self.tmp / "out"
        with mock.patch("builtins.print"):
            code = render.main(["--out", str(out), "--manifest", str(mpath), "--dry-run", "--proxy"])
        self.assertEqual(code, 0)
        planned = json.loads((out / "render_plan.json").read_text(encoding="utf-8"))
        s07 = next(s for s in planned["shots"] if s["shot_id"] == last["shot_id"])
        self.assertEqual((s07["asset"]["id"], s07["storyboard_asset_id"]), ("owner-s07-portrait", last["asset_id"]))


def _have_render_tools():
    try:
        render.find_fonts()
    except render.RenderError:
        return False
    return render.ffmpeg_available()


@unittest.skipUnless(_have_render_tools(), "ffmpeg/ffprobe or DejaVu fonts not installed: render test skipped")
class EndToEndRenderTest(Fixture):
    """A real 3-second, 2-shot film at 320x180 through the same CLI as the 45 s film, then QA."""

    def short_pack(self):
        sb, bible = copy.deepcopy(self.sb), copy.deepcopy(self.bible)
        for doc in (sb, bible):
            doc["format"]["seconds"] = 3
        sb["shots"] = sb["shots"][:2]
        sb["shots"][0].update(duration_sec=1, end_sec=1)
        sb["shots"][1].update(start_sec=1, duration_sec=2, end_sec=3)
        for name, doc in (("storyboard.json", sb), ("film_bible.json", bible)):
            (self.tmp / name).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        return sb, bible

    def test_render_qa_and_single_shot_rerender(self):
        sb, bible = self.short_pack()
        out = self.tmp / "out"
        shots = procedural.shots_from_shotpack(sb, self.cand)
        manifest = procedural.generate(out / "assets", shots, sb["project_id"])
        overrides = {s["shot_id"]: f"orig-{s['shot_id']}-{s['role']}" for s in shots}
        p = build_plan(sb, bible, manifest, manifest_dir=out / "assets", size=(320, 180), overrides=overrides)
        recs = render.render_shots(p, manifest_dir=out / "assets", work=out)
        self.assertEqual([r["status"] for r in recs], ["rendered", "rendered"])
        film = out / "film.mp4"
        render.run(render.assemble_command(p, [out / r["clip"] for r in recs], film), out)
        receipt = qa.run_qa(film, p, recs, manifest_dir=out / "assets", frames_dir=out / "frames")
        failed = [c for c in receipt["checks"] if c["result"] != "PASS"]
        self.assertEqual(receipt["status"], "PASS", failed)
        self.assertEqual(str(receipt["film"]["frames"]), "72")
        self.assertEqual(receipt["cost"]["usd"], 0.0)
        self.assertEqual(receipt["milestones"]["realistic_photo_film"], "BLOCKED")
        self.assertEqual(receipt["voice"]["source"], "none")
        again = render.render_shots(p, manifest_dir=out / "assets", work=out, only=["s02"])
        self.assertEqual([r["status"] for r in again], ["cached", "rendered"])
        self.assertEqual(again[0]["clip_sha256"], recs[0]["clip_sha256"])

    def test_render_with_narration_meets_loudness(self):
        sb, bible = self.short_pack()
        out = self.tmp / "out"
        shots = procedural.shots_from_shotpack(sb, self.cand)
        manifest = procedural.generate(out / "assets", shots, sb["project_id"])
        overrides = {s["shot_id"]: f"orig-{s['shot_id']}-{s['role']}" for s in shots}
        p = build_plan(sb, bible, manifest, manifest_dir=out / "assets", size=(320, 180), overrides=overrides)
        vdir = self.tmp / "vo"
        vdir.mkdir()
        doc = narration.load(narration_doc(vdir, sb["project_id"], {"s01": 0.5, "s02": 1.4}), p)
        recs = render.render_shots(p, manifest_dir=out / "assets", work=out)
        film = out / "film.mp4"
        render.run(render.assemble_command(p, [out / r["clip"] for r in recs], film, doc["lines"]), out)
        receipt = qa.run_qa(film, p, recs, manifest_dir=out / "assets", frames_dir=out / "frames", narration=doc)
        failed = [c for c in receipt["checks"] if c["result"] != "PASS"]
        self.assertEqual(receipt["status"], "PASS", failed)
        self.assertEqual(receipt["milestones"]["narration"], "PASS")
        self.assertEqual(receipt["voice"]["source"], "piper")
        self.assertTrue(-18.0 <= receipt["loudness"]["integrated_lufs"] <= -14.0, receipt["loudness"])

    def test_failed_render_raises(self):
        sb, bible = self.short_pack()
        data = b"not a png"
        assets = []
        for s in sb["shots"]:
            (self.tmp / f"{s['asset_id']}.png").write_bytes(data)
            assets.append(verified_asset(s["asset_id"], f"{s['asset_id']}.png", data))
        m = {"schema": "film-studio/asset-manifest/v1", "project_id": sb["project_id"], "assets": assets}
        p = build_plan(sb, bible, m, manifest_dir=self.tmp, size=(320, 180))
        with self.assertRaises(render.RenderError):
            render.render_shots(p, manifest_dir=self.tmp, work=self.tmp / "out")


if __name__ == "__main__":
    unittest.main(verbosity=2)
