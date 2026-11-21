"""Job contract of the AI Media Finisher (GitHub #427, R-0089): stage order, artifacts, undo, fail-closed source.

Every FFmpeg/Whisper call is replaced by a stand-in, so this proves the orchestration and the evidence files, NOT a
render: no real MP4 is produced here. A real render needs the worker image (FFmpeg, faster-whisper, Remotion).
"""
import json
import os
import sys
import tempfile
import types
from pathlib import Path

os.environ["FINISHER_DATA_DIR"] = tempfile.mkdtemp(prefix="finisher-contract-")
STUBBED = False
try:
    import fastapi  # noqa: F401
    import pydantic  # noqa: F401
except ImportError:
    # A bare host (the EC2 agent runner) has no FastAPI; the functions under test do not use it.
    STUBBED = True

    class _App:
        def __init__(self, *args, **kwargs):
            pass

        def _decorator(self, *args, **kwargs):
            return lambda fn: fn
        on_event = get = post = _decorator

    class _HTTPException(Exception):
        def __init__(self, status_code, detail=""):
            super().__init__(detail)
            self.status_code = status_code

    _fastapi = types.ModuleType("fastapi")
    _fastapi.FastAPI, _fastapi.HTTPException = _App, _HTTPException
    _fastapi.BackgroundTasks = _fastapi.Request = object
    _responses = types.ModuleType("fastapi.responses")
    _responses.FileResponse = object
    _pydantic = types.ModuleType("pydantic")
    _pydantic.BaseModel = object
    sys.modules.update({"fastapi": _fastapi, "fastapi.responses": _responses, "pydantic": _pydantic})

import media_finisher_worker.app as worker  # noqa: E402

DATA = Path(os.environ["FINISHER_DATA_DIR"])
WORDS = [{"word": "Hello", "start": 0.0, "end": 0.4, "confidence": .99}, {"word": "world.", "start": 0.45, "end": 0.9, "confidence": .99},
         {"word": "um", "start": 2.2, "end": 2.4, "confidence": .9}, {"word": "Next", "start": 2.5, "end": 2.9, "confidence": .99},
         {"word": "point", "start": 2.95, "end": 3.4, "confidence": .99}]
PROBE = {"duration": 4.0, "width": 1080, "height": 1920, "fps": "30/1", "video_codec": "h264", "audio_codec": "aac",
         "video_duration": 4.0, "audio_duration": 4.0, "audio_channels": 2}
REQUEST = {"input_url": "https://media.example.invalid/signed/source.mp4?token=SECRET-TOKEN", "options": {}, "content_package": {},
           "platform": "reels", "profile": {"id": "talking_head_fast", "version": 1, "config": {
               "speech_cleanup": {"silence_trim": True, "pause_threshold_sec": 0.4, "pre_handle_sec": 0.1, "post_handle_sec": 0.15},
               "captions": {"max_words": 3}, "safe_zones": {"top": .12, "bottom": .20, "right": .12, "left": 0}}}}
calls = []
final = {"duration": 0.0, "decode": {"status": "pass", "detail": "stand-in"}}


def touch(path):
    Path(path).write_bytes(b"x" * 2048)


def fake_probe(path):
    name = Path(path).name
    if name in ("final.mp4", "clean.mp4"):
        return {**PROBE, "duration": final["duration"], "video_duration": final["duration"], "audio_duration": final["duration"]}
    return dict(PROBE)


def fake_apply(job_id, src, dest, duration, cuts, profile):
    calls.append("cut")
    final["duration"] = duration - sum(c["end"] - c["start"] for c in cuts)
    touch(dest)


def fake_audio(src, dest, profile):
    calls.append("audio")
    touch(dest)
    return {"target_voice_lufs": -14.0, "voice_lufs": -14.2, "measured": {}, "music_applied": False}


def fake_render(job_id, clean, dest, *rest):
    calls.append("render")
    touch(dest)


worker.LOW_MEMORY_MODE = True  # the FFmpeg overlay engine; the Remotion engine needs Node and Chromium
worker._probe = fake_probe
worker._download = lambda url, dest: touch(dest)
worker._normalize_input = lambda job_id, src, dest, profile: touch(dest)
worker._extract_audio = lambda src, wav: touch(wav)
worker._transcribe_words = lambda job_id, wav: (WORDS, {"language": "en", "model": "stand-in"})
worker._detect_silences = lambda src, threshold: [{"start": 0.95, "end": 2.15, "reason": "silence>0.40s"}]
worker._apply_cuts = fake_apply
worker._render_ffmpeg_fast = fake_render
worker._audio_finish = fake_audio
worker._final_media_checks = lambda path, duration: {"decode": dict(final["decode"]), "black": {"status": "pass"}, "silence": {"status": "pass"}}
worker._frame_sampling_report = lambda *args: {"method": "stand-in", "captured": 0, "samples": []}


def run(job_id, request=REQUEST):
    worker._write_state(job_id, replace={"id": job_id, "status": "queued", "request": json.loads(json.dumps(request)), "callback_url": ""})
    worker._process_one(job_id)
    return worker._read_state(job_id)


# 1. A good source: ready, every evidence file on disk, working copies removed, the source kept.
done = run("job-ok")
assert done["status"] == "ready", done.get("error")
assert calls == ["cut", "render", "audio"], calls
report = done["report"]
files = {p.name for p in (DATA / "job-ok").iterdir()}
expected = {"source-reference.json", "transcript.json", "edit-decisions.json", "timeline.json", "qa-report.json", "render-metrics.json",
            "captions.srt", "final.mp4", "source.bin"}
assert expected <= files, sorted(expected - files)
assert not files & {"normalized.mp4", "clean.mp4", "composed.mp4", "audio.wav"}, sorted(files)
# The signed link never reaches an artifact: only its host is recorded.
reference = (DATA / "job-ok" / "source-reference.json").read_text(encoding="utf-8")
assert "SECRET-TOKEN" not in reference and "SECRET-TOKEN" not in json.dumps(report) and report["source_reference"]["source_host"] == "media.example.invalid"
assert len(report["source_reference"]["sha256"]) == 64 and report["source_reference"]["original_modified"] is False

# 2. Cuts are word-safe and every removed word is named; the pause after "world." keeps its longer breath, and the
#    wordless sliver between the pause cut and the filler cut is not left behind as a flash shot.
assert report["cut_list"] == [{"start": 1.15, "end": 2.448, "reason": "silence>0.40s+filler_word:um", "decision_ids": ["d001", "d002"]}], report["cut_list"]
audit = report["qa_report"]["word_audit"]
assert audit["ok"] and [x["word"] for x in audit["removed_words"]] == ["um"] and audit["kept_words"] == 4
assert report["edit_decisions"]["summary"]["applied_by_kind"] == {"silence": 1, "filler": 1, "duplicate": 0}
assert report["qa_report"]["overall"] == "pass" and report["qa_report"]["human_review_required"] is True
assert {c["id"] for c in report["qa_report"]["checks"]} == {"source_valid", "final_decodes", "words_at_cuts", "captions_timeline", "length_matches_cut_list",
                                                           "audio_video_streams", "black_frames", "silent_stretches", "voice_loudness", "caption_safe_zones",
                                                           "wordless_slivers", "long_pauses_kept"}
assert report["safe_zone_report"]["method"] == "estimated_caption_bbox_v1" and report["safe_zone_report"]["violations"] == []

# 3. Captions never cross the cut and never overlap; the timeline maps output time back to source time.
captions = report["caption_timeline"]
assert [c["text"] for c in captions] == ["Hello world.", "Next point"], captions
assert captions[0]["end"] <= 1.15 <= captions[1]["start"]
timeline = json.loads((DATA / "job-ok" / "timeline.json").read_text(encoding="utf-8"))
assert timeline["keep_ranges"] == [{"source_start": 0.0, "source_end": 1.15, "output_start": 0.0},
                                   {"source_start": 2.448, "source_end": 4.0, "output_start": 1.15}], timeline["keep_ranges"]
metrics = report["render_metrics"]
assert list(metrics["stage_seconds"]) == ["download", "validate", "normalize", "transcript", "cleanup", "graphics", "render", "audio", "qa"]
assert metrics["measured_cost_usd"] == 0.0 and metrics["final_bytes"] == 2048

# 4. Reviewer undo through options.edit_overrides: the filler cut is restored, the pause cut stays.
request = json.loads(json.dumps(REQUEST))
request["options"] = {"edit_overrides": {"restore_ids": ["d002"]}}
undone = run("job-undo", request)["report"]
assert [(d["id"], d["kept_reason"]) for d in undone["edit_decisions"]["decisions"] if not d["applied"]] == [("d002", "restored_by_reviewer")]
assert undone["qa_report"]["word_audit"]["removed_words"] == [] and undone["qa_report"]["word_audit"]["ok"]

# 5. A final file that does not decode is never handed to approval.
final["decode"] = {"status": "fail", "detail": "Invalid data found when processing input"}
broken = run("job-bad-final")
assert broken["status"] == "failed" and broken["failed_stage"] == "qa" and "decode check" in broken["error"], broken
assert not broken.get("final_url") and not (DATA / "job-bad-final" / "final.mp4").exists()
final["decode"] = {"status": "pass", "detail": "stand-in"}

# 6. A broken source fails closed before any processing, with the stage and a readable reason.
calls.clear()
worker._probe = lambda path: {"duration": 0.0, "width": 0, "height": 0, "fps": "0/1", "video_codec": "", "audio_codec": ""}
bad = run("job-bad-source")
assert bad["status"] == "failed" and bad["failed_stage"] == "validate" and bad["error"].startswith("Unsupported source: "), bad
assert calls == [] and not (DATA / "job-bad-source" / "final.mp4").exists() and not (DATA / "job-bad-source" / "source-reference.json").exists()


def unreadable(path):
    raise RuntimeError("ffprobe: moov atom not found")


worker._probe = unreadable
assert run("job-unreadable")["error"] == "Unsupported source: FFprobe could not read the file"

# 7. A retry of the same source after a failure starts clean and succeeds (stand-ins restored).
worker._probe = fake_probe
retried = run("job-bad-source")
assert retried["status"] == "ready" and retried["failed_stage"] == "" and retried["error"] == ""

# 8. A user's video is private (#427 follow-up): job files open only with the API token or a signed link for exactly
#    that file that has not expired; job ids are never paths.
class Req:
    def __init__(self, bearer=""):
        self.headers = {"authorization": "Bearer " + bearer} if bearer else {}


def status_of(fn, *a, **k):
    try:
        fn(*a, **k)
    except worker.HTTPException as exc:
        return exc.status_code
    return 200


served = []
worker.FileResponse = lambda path, **kw: served.append(Path(path).name) or "file"
JOB = "job-bad-source"                                   # finished in step 7, final.mp4 exists
assert (DATA / JOB / "final.mp4").exists()
worker.API_TOKEN, worker.ALLOW_PUBLIC_FILES = "", False
assert status_of(worker.file, JOB, "final.mp4", Req()) == 403            # no token configured: closed, not open
worker.ALLOW_PUBLIC_FILES = True
assert status_of(worker.file, JOB, "final.mp4", Req()) == 200            # explicit local-development switch only
worker.ALLOW_PUBLIC_FILES = False
worker.API_TOKEN = "t0ken-for-the-test"
assert status_of(worker.file, JOB, "final.mp4", Req()) == 403            # a known job id is not enough
assert status_of(worker.file, JOB, "final.mp4", Req("wrong")) == 403
assert status_of(worker.file, JOB, "final.mp4", Req("t0ken-for-the-test")) == 200
link = worker._public_file(JOB, "final.mp4")
exp = int(link.split("exp=")[1].split("&")[0]); sig = link.split("sig=")[1]
assert link.startswith(worker.PUBLIC_BASE_URL + f"/files/{JOB}/final.mp4?exp=") and "t0ken" not in link
assert 0 < exp - worker.time.time() <= worker.FILE_URL_TTL_SEC
assert status_of(worker.file, JOB, "final.mp4", Req(), exp=exp, sig=sig) == 200          # the signed link plays
assert status_of(worker.file, JOB, "captions.srt", Req(), exp=exp, sig=sig) == 403       # ...for that file only
assert status_of(worker.file, "job-ok", "final.mp4", Req(), exp=exp, sig=sig) == 403     # ...of that job only
assert status_of(worker.file, JOB, "final.mp4", Req(), exp=exp + 60, sig=sig) == 403     # the expiry is signed too
assert status_of(worker.file, JOB, "final.mp4", Req(), exp=exp, sig=sig[:-1] + ("0" if sig[-1] != "0" else "1")) == 403
old_sig = worker._file_signature(JOB, "final.mp4", 1_000)
assert status_of(worker.file, JOB, "final.mp4", Req(), exp=1_000, sig=old_sig) == 403    # expired
assert status_of(worker.file, JOB, "state.json", Req("t0ken-for-the-test")) == 404       # still only the listed files
assert status_of(worker.file, JOB, "source.bin", Req("t0ken-for-the-test")) == 404
for bad in ("..", ".", "a/b", "../etc", "job id", "", "x" * 81, "-lead"):
    assert status_of(worker._job_dir, bad) == 400, bad
    assert status_of(worker.file, bad, "final.mp4", Req("t0ken-for-the-test")) == 400, bad
assert status_of(worker._job_dir, "3f2c9a1e-7b1d-4c55-9a51-0a1b2c3d4e5f") == 200          # the ids FactoryOS sends
assert served.count("final.mp4") == 3
state_again = worker.job_status(JOB, Req("t0ken-for-the-test"))
assert "sig=" in state_again["final_url"] and status_of(worker.job_status, JOB, Req()) == 401   # a fresh signed link per read
worker.API_TOKEN = ""

if STUBBED:
    import media_finisher_worker.test_planner  # noqa: F401  the planner tests need the same stand-in on a bare host
print("Media Finisher pipeline contract tests passed" + (" (FastAPI stand-in)" if STUBBED else ""))
