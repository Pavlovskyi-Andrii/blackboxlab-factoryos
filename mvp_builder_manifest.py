"""MVP Builder M1C (#274): the verifiable output manifest an isolated Builder run hands to QA (#186 spec).

Pure and offline: it validates and normalises what a Builder *says* it produced. It never calls GitHub, never
reads credentials, never deploys and never calls the clock (``now`` is a parameter). A manifest that is not
acceptable gets every reason at once, as ``{"code", "field"}`` dicts.

Example::

    from mvp_builder_manifest import validate, to_json
    result = validate(raw, request=normalised_build_request, now="2026-11-08T12:00:00Z")
    if result.ok and result.manifest["ready_for_qa"]:
        stored = to_json(result.manifest)

Rules:
- ``schema_version`` is exactly ``mvp-build-manifest/1``. Unknown fields are refused, input is never mutated.
- ``project_id``, ``product_version``, ``task_id``, ``run_id`` use the build_request conventions; when the
  originating normalised request is passed they must match it (``project_mismatch``, ``version_mismatch``,
  ``task_mismatch``, ``run_id_mismatch``). A request without a run_id cannot have produced this manifest.
- ``producer_role`` is the Builder lane (``claude``).
- ``branch`` is a safe ref name (no ``..``, spaces, ``@{``, ``.lock``); ``main``/``master`` is ``branch_is_default``.
- ``commit_sha`` is 40 lowercase hex (``bad_commit_sha``).
- ``pr_url`` is exactly ``https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/pull/<n>``; any other
  scheme, host, repo or lookalike is ``counterfeit_link``. Evidence refs (``ci_run``, ``pr``, ``commit``, ``file``,
  ``url``) obey the same rule: lookalike hosts, userinfo tricks and other repos on github.com are refused.
- ``tests`` is a non-empty list of ``{command, result: passed|failed|not_run, ran_at?, output_sha256?}``. A
  passed or failed test without ``ran_at`` is ``fabricated_test``; a ``not_run`` test with one is ``bad_test``;
  ``ran_at`` after the reference time is ``future_ran_at``; repeated commands are ``duplicate_test``. With a
  request, every requested test command must be present (``missing_required_test``).
- ``qa_criteria`` is a non-empty list of ``{criterion, status: met|not_met|unknown}``; with a request every
  acceptance criterion must be covered. Otherwise ``missing_qa_criteria``.
- ``human_review`` is ``pending|approved|changes_requested|unknown``; ``preview`` is ``{kind: none|local|verified,
  url?}``: ``verified`` needs an https url, ``local`` may only point at localhost, ``none`` has no url.
- A PR URL or commit is NOT proof of merge or deploy. ``merge_state`` and ``deploy_state`` are always
  ``UNKNOWN`` and evidence ``state`` is always ``UNKNOWN``; ``ready_for_qa`` and ``state`` are derived. Input that
  asserts otherwise (``merged: true``, ``deployed``, ``state: "merged"``, evidence ``state: "verified"``...) is
  ``unverifiable_claim``.
- ``ready_for_qa`` is True only when every test passed, no QA criterion is ``not_met`` and there is no
  ``blocked_reason``; a failed test leaves the manifest valid but not ready.
- Free text that looks like a credential (``ghp_``, ``sk-``, ``password=``...) is ``secret_in_text``.
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlsplit

from mvp_builder_request import BUILDER_LANE, _path_problem

SCHEMA_VERSION = "mvp-build-manifest/1"
REPO = "Pavlovskyi-Andrii/blackboxlab-factoryos"
UNKNOWN = "UNKNOWN"
TEST_RESULTS = ("passed", "failed", "not_run")
QA_STATUSES = ("met", "not_met", "unknown")
HUMAN_REVIEW = ("pending", "approved", "changes_requested", "unknown")
PREVIEW_KINDS = ("none", "local", "verified")
EVIDENCE_KINDS = ("ci_run", "pr", "commit", "file", "url")
DEFAULT_BRANCHES = ("main", "master")
MAX_LIST = 50
MAX_TEXT = 300

FIELDS = ("schema_version", "project_id", "product_version", "task_id", "run_id", "producer_role", "branch",
          "commit_sha", "pr_url", "tests", "evidence_refs", "qa_criteria", "human_review", "reviewer", "preview",
          "blocked_reason", "created_at")
DERIVED = ("merge_state", "deploy_state", "ready_for_qa", "state")
CLAIMS = ("merged", "deployed", "merged_at", "deployed_at", "is_merged", "is_deployed", "production_url",
          "deploy_url", "ci_passed", "verified")

_PROJECT = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
_VERSION = re.compile(r"^v\d{1,3}(\.\d{1,3}){0,2}$")
_TASK = re.compile(r"^[A-Z]{1,6}-\d{1,6}$")
_RUN = re.compile(r"^run-[0-9a-f]{8,32}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$")
_PR = re.compile(r"^https://github\.com/" + re.escape(REPO) + r"/pull/[1-9]\d{0,5}$")
_CI = re.compile(r"^https://github\.com/" + re.escape(REPO) + r"/actions/runs/[1-9]\d{0,14}(/job/[1-9]\d{0,14})?$")
_REPO_URL = re.compile(r"^https://github\.com/" + re.escape(REPO) + r"(/[A-Za-z0-9._~%/#?=&-]*)?$")
_SECRET = re.compile(r"(ghp_|gho_|github_pat_|sk-[A-Za-z0-9]|xox[abp]-|AKIA[0-9A-Z]{12}|-----BEGIN|"
                     r"(password|passwd|secret|token|api_key|apikey)\s*[=:])", re.IGNORECASE)
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]")


@dataclass
class Result:
    ok: bool
    manifest: Optional[dict] = None
    reasons: list = field(default_factory=list)

    @property
    def codes(self) -> list:
        return [r["code"] for r in self.reasons]


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _stamp(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not _STAMP.match(value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _link_problem(url: Any, pattern: "re.Pattern") -> Optional[str]:
    """None if ``url`` matches ``pattern`` exactly; otherwise counterfeit_link (or bad_link if not a string)."""
    if not isinstance(url, str) or not url.strip() or len(url) > MAX_TEXT or re.search(r"\s", url):
        return "bad_link"
    return None if pattern.match(url) else "counterfeit_link"


def _url_problem(url: Any) -> Optional[str]:
    """Generic https evidence url: refuse userinfo, lookalike GitHub hosts and other repos on github.com."""
    if not isinstance(url, str) or not url.strip() or len(url) > MAX_TEXT or re.search(r"\s", url):
        return "bad_link"
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
    except ValueError:
        return "counterfeit_link"
    if parts.scheme != "https" or not host or "@" in parts.netloc or "\\" in url:
        return "counterfeit_link"
    if host == "github.com" or host == "www.github.com":
        return None if _REPO_URL.match(url) else "counterfeit_link"
    if "github" in host and not host.endswith(".githubusercontent.com"):
        return "counterfeit_link"          # github.com.evil.com, githubb.com, github-com.io ...
    if host.startswith("xn--") or ".xn--" in host:
        return "counterfeit_link"          # punycode lookalikes
    return None


def redacted_example() -> dict:
    """A well-formed, fake manifest (no real SHA, run or PR) for docs and tests."""
    return {
        "schema_version": SCHEMA_VERSION, "project_id": "mycast", "product_version": "v1", "task_id": "T-0001",
        "run_id": "run-0123abcd", "producer_role": "claude", "branch": "claude/t-0001-example",
        "commit_sha": "0" * 39 + "1",
        "pr_url": "https://github.com/" + REPO + "/pull/1",
        "tests": [{"command": "python test_example.py", "result": "passed", "ran_at": "2026-11-08T10:00:00Z",
                   "output_sha256": "a" * 64}],
        "evidence_refs": [{"kind": "ci_run", "ref": "https://github.com/" + REPO + "/actions/runs/1"},
                          {"kind": "file", "ref": "test_example.py"}],
        "qa_criteria": [{"criterion": "Example criterion holds", "status": "met"}],
        "human_review": "pending", "reviewer": None, "preview": {"kind": "none"}, "blocked_reason": None,
        "created_at": "2026-11-08T10:05:00Z"}


def validate(raw: Any, *, request: Optional[dict] = None, now: Optional[str] = None) -> Result:
    """Check a raw output manifest. Returns every problem, never raises on bad input, never mutates ``raw``.

    ``request`` is the originating normalised build_request; ``now`` (ISO UTC Z) is the reference time for
    ``ran_at``/``created_at``. Without ``now`` the manifest's own ``created_at`` is the reference."""
    reasons: list = []

    def bad(code: str, name: str) -> None:
        reasons.append({"code": code, "field": name})

    if not isinstance(raw, dict):
        return Result(False, None, [{"code": "not_an_object", "field": ""}])
    raw = copy.deepcopy(raw)
    for key in sorted(set(raw) - set(FIELDS) - set(DERIVED)):
        bad("unverifiable_claim" if key.lower() in CLAIMS else "unknown_field", key)
    for key in ("merge_state", "deploy_state"):
        if key in raw and raw[key] != UNKNOWN:
            bad("unverifiable_claim", key)       # a manifest is never proof of merge / deploy

    if raw.get("schema_version") != SCHEMA_VERSION:
        bad("unknown_schema_version", "schema_version")

    project = _text(raw.get("project_id"))
    if not _PROJECT.match(project):
        bad("bad_project_id", "project_id")
    version = _text(raw.get("product_version")).lower()
    if not _VERSION.match(version):
        bad("bad_product_version", "product_version")
    task = _text(raw.get("task_id"))
    if not _TASK.match(task):
        bad("bad_task_id", "task_id")
    run = raw.get("run_id")
    if not (isinstance(run, str) and _RUN.match(run)):
        bad("bad_run_id", "run_id")
    if _text(raw.get("producer_role")).lower() != BUILDER_LANE:
        bad("bad_producer", "producer_role")

    if request is not None:
        if not isinstance(request, dict):
            bad("bad_request", "request")
        else:
            for name, value, code in (("project_id", project, "project_mismatch"),
                                      ("product_version", version, "version_mismatch"),
                                      ("task_id", task, "task_mismatch"), ("run_id", run, "run_id_mismatch")):
                if request.get(name) is None or request.get(name) != value:
                    bad(code, name)

    branch = _text(raw.get("branch"))
    if branch in DEFAULT_BRANCHES:
        bad("branch_is_default", "branch")
    elif (not _BRANCH.match(branch) or ".." in branch or "//" in branch or "@{" in branch
          or branch.endswith(("/", ".", ".lock")) or "/." in branch):
        bad("bad_branch", "branch")

    sha = raw.get("commit_sha")
    if not (isinstance(sha, str) and _SHA.match(sha)) or sha == "0" * 40:
        bad("bad_commit_sha", "commit_sha")

    pr_url = raw.get("pr_url")
    if pr_url is None or pr_url == "":
        bad("missing_pr_url", "pr_url")
    else:
        problem = _link_problem(pr_url, _PR)
        if problem:
            bad(problem, "pr_url")

    stamp = _text(raw.get("created_at"))
    created = _stamp(stamp)
    if created is None:
        bad("bad_created_at", "created_at")
    reference = created
    if now is not None:
        reference = _stamp(now)
        if reference is None:
            bad("bad_now", "now")
        elif created is not None and created > reference:
            bad("future_created_at", "created_at")

    tests: list = []
    tests_raw = raw.get("tests")
    if not isinstance(tests_raw, list) or not tests_raw:
        bad("missing_tests", "tests")
    elif len(tests_raw) > MAX_LIST:
        bad("bad_test", "tests")
    else:
        seen: set = set()
        for i, t in enumerate(tests_raw):
            where = "tests[%d]" % i
            if not isinstance(t, dict) or set(t) - {"command", "result", "ran_at", "output_sha256"}:
                bad("bad_test", where)
                continue
            command = _text(t.get("command"))
            result = t.get("result")
            ran_at = t.get("ran_at")
            digest = t.get("output_sha256")
            if not command or len(command) > MAX_TEXT or "\n" in command or "`" in command or "$(" in command:
                bad("bad_test", where + ".command")
            elif command in seen:
                bad("duplicate_test", where + ".command")
            seen.add(command)
            if result not in TEST_RESULTS:
                bad("bad_test_result", where + ".result")
            if result == "not_run":
                if ran_at is not None or digest is not None:
                    bad("bad_test", where + ".ran_at")
            elif result in ("passed", "failed"):
                if ran_at is None or ran_at == "":
                    bad("fabricated_test", where + ".ran_at")      # a result with no run behind it
                else:
                    when = _stamp(ran_at)
                    if when is None:
                        bad("bad_ran_at", where + ".ran_at")
                    elif reference is not None and when > reference:
                        bad("future_ran_at", where + ".ran_at")
            if digest is not None and not (isinstance(digest, str) and _SHA256.match(digest)):
                bad("bad_output_sha256", where + ".output_sha256")
            entry = {"command": command, "result": result, "ran_at": ran_at, "output_sha256": digest}
            tests.append(entry)
        if isinstance(request, dict) and isinstance(request.get("test_commands"), list):
            for command in request["test_commands"]:
                if command not in seen:
                    bad("missing_required_test", "tests")
    tests.sort(key=lambda x: x["command"])

    qa: list = []
    qa_raw = raw.get("qa_criteria")
    if not isinstance(qa_raw, list) or not qa_raw:
        bad("missing_qa_criteria", "qa_criteria")
    elif len(qa_raw) > MAX_LIST:
        bad("bad_qa_criterion", "qa_criteria")
    else:
        for i, c in enumerate(qa_raw):
            criterion = _text(c.get("criterion")) if isinstance(c, dict) else ""
            if (not isinstance(c, dict) or set(c) - {"criterion", "status"} or not criterion
                    or len(criterion) > MAX_TEXT or "\n" in criterion or c.get("status") not in QA_STATUSES):
                bad("bad_qa_criterion", "qa_criteria[%d]" % i)
                continue
            qa.append({"criterion": criterion, "status": c["status"]})
        if isinstance(request, dict) and isinstance(request.get("acceptance_criteria"), list):
            covered = {c["criterion"] for c in qa}
            for criterion in request["acceptance_criteria"]:
                if criterion not in covered:
                    bad("missing_qa_criteria", "qa_criteria")
    qa.sort(key=lambda x: x["criterion"])

    evidence: list = []
    ev_raw = raw.get("evidence_refs", [])
    if not isinstance(ev_raw, list) or len(ev_raw) > MAX_LIST:
        bad("bad_evidence_ref", "evidence_refs")
    else:
        for i, e in enumerate(ev_raw):
            where = "evidence_refs[%d]" % i
            if not isinstance(e, dict) or set(e) - {"kind", "ref", "state"}:
                bad("bad_evidence_ref", where)
                continue
            if "state" in e and e["state"] != UNKNOWN:
                bad("unverifiable_claim", where + ".state")        # evidence is never self-certified
            kind, ref = e.get("kind"), e.get("ref")
            if kind == "ci_run":
                problem = _link_problem(ref, _CI)
            elif kind == "pr":
                problem = _link_problem(ref, _PR)
            elif kind == "commit":
                problem = None if isinstance(ref, str) and _SHA.match(ref) else "bad_commit_sha"
            elif kind == "file":
                problem = _path_problem(ref) and "bad_evidence_ref"
                if isinstance(ref, str) and _path_problem(ref) == "secret_path":
                    problem = "secret_path"
            elif kind == "url":
                problem = _url_problem(ref)
            else:
                problem = "bad_evidence_ref"
            if problem:
                bad(problem, where)
            else:
                evidence.append({"kind": kind, "ref": ref.strip(), "state": UNKNOWN})
    evidence.sort(key=lambda x: (x["kind"], x["ref"]))

    review = _text(raw.get("human_review")).lower()
    if review not in HUMAN_REVIEW:
        bad("bad_human_review", "human_review")
    reviewer = raw.get("reviewer")
    if reviewer is not None and (not _text(reviewer) or len(reviewer) > 80 or "\n" in reviewer):
        bad("bad_reviewer", "reviewer")
    reviewer = _text(reviewer) or None

    preview_raw = raw.get("preview")
    preview: dict = {"kind": "none"}
    if not isinstance(preview_raw, dict) or set(preview_raw) - {"kind", "url"} \
            or preview_raw.get("kind") not in PREVIEW_KINDS:
        bad("bad_preview", "preview")
    else:
        kind, url = preview_raw["kind"], preview_raw.get("url")
        if kind == "none":
            if url is not None:
                bad("bad_preview", "preview.url")
        elif kind == "verified":
            problem = _url_problem(url) if url else "bad_preview"
            if problem:
                bad(problem if problem == "counterfeit_link" else "bad_preview", "preview.url")
            elif (urlsplit(url).hostname or "").lower() in ("localhost", "127.0.0.1", "::1"):
                bad("bad_preview", "preview.url")
            else:
                preview = {"kind": kind, "url": url}
        else:   # local: never a public url
            if url is None:
                preview = {"kind": kind}
            else:
                try:
                    parts = urlsplit(url) if isinstance(url, str) else None
                    host = parts.netloc.rsplit(":", 1)[0].lower() if parts else ""
                except ValueError:
                    parts, host = None, ""
                if not parts or parts.scheme not in ("http", "https") or host not in _LOCAL_HOSTS:
                    bad("bad_preview", "preview.url")
                else:
                    preview = {"kind": kind, "url": url}

    blocked = raw.get("blocked_reason")
    if blocked is not None and (not _text(blocked) or len(blocked) > MAX_TEXT):
        bad("bad_blocked_reason", "blocked_reason")
    blocked = _text(blocked) or None

    texts = [t["command"] for t in tests] + [c["criterion"] for c in qa] + [blocked or "", reviewer or ""]
    if any(_SECRET.search(t) for t in texts):
        bad("secret_in_text", "")

    ready = (bool(tests) and all(t["result"] == "passed" for t in tests)
             and not any(c["status"] == "not_met" for c in qa) and blocked is None)
    state = "blocked" if blocked else ("qa_review" if ready else "pr_open")
    if "ready_for_qa" in raw and raw["ready_for_qa"] is not ready:
        bad("unverifiable_claim", "ready_for_qa")
    if "state" in raw and raw["state"] != state:
        bad("unverifiable_claim", "state")

    if reasons:
        return Result(False, None, reasons)
    manifest = {"schema_version": SCHEMA_VERSION, "project_id": project, "product_version": version,
                "task_id": task, "run_id": run, "producer_role": BUILDER_LANE, "branch": branch,
                "commit_sha": sha, "pr_url": pr_url, "tests": tests, "evidence_refs": evidence,
                "qa_criteria": qa, "human_review": review, "reviewer": reviewer, "preview": preview,
                "blocked_reason": blocked, "created_at": stamp,
                "merge_state": UNKNOWN, "deploy_state": UNKNOWN, "ready_for_qa": ready, "state": state}
    return Result(True, manifest, [])


def to_json(manifest: dict) -> str:
    """Stable serialisation: sorted keys, no spaces, UTF-8 kept."""
    return json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def from_json(text: str, *, request: Optional[dict] = None, now: Optional[str] = None) -> Result:
    """Parse and re-validate; a stored manifest is never trusted blindly."""
    try:
        raw = json.loads(text)
    except (TypeError, ValueError):
        return Result(False, None, [{"code": "bad_json", "field": ""}])
    return validate(raw, request=request, now=now)
