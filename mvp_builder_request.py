"""MVP Builder M1A (#272): the versioned ``build_request`` contract from the #186 technical spec.

Pure and offline: it validates and normalises a request, nothing more. It never claims a Relay task, never runs a
worker, never calls the network and never invents a run_id. A request that is not acceptable gets every reason at
once, as machine-readable codes, so MVP Manager can show the owner exactly what is missing.

Example::

    from mvp_builder_request import validate, to_json
    result = validate(raw)
    if result.ok:
        stored = to_json(result.request)        # stable bytes: same input -> same JSON
    else:
        print([r["code"] for r in result.reasons])   # e.g. ["missing_owner_spec", "missing_acceptance"]

Rules (spec 2026-11-06, issuecomment-6684703331):
- ``schema_version`` must be exactly ``mvp-build-request/1``; anything else is ``unknown_schema_version``.
- The request must link an owner-approved spec in this repository (issue, PR or issue comment) and say it is
  approved; otherwise ``missing_owner_spec`` / ``bad_spec_link`` / ``spec_not_owner_approved`` (``needs_owner``).
- The Builder lane is Claude's: another ``owner_lane`` is ``wrong_owner_lane``.
- ``files_scope`` holds relative repository paths. Absolute paths, ``..``, backslashes, the repository root or a
  root wildcard (``*``, ``**``, ``*.py``), ``.git/`` and ``.env`` files are refused.
- At least one acceptance criterion and one test command are required.
- Zero spend: ``budget_cap_usd`` is 0 and every permission flag (paid API, publish, outreach, cloud, main push,
  auto-merge) is false.
- ``run_id`` is optional: an unclaimed request has none. If present it must look like a Relay run id.
- Unknown fields are refused rather than silently dropped.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

SCHEMA_VERSION = "mvp-build-request/1"
BUILDER_LANE = "claude"
LANES = ("claude", "chatgpt", "gemini")
PRIORITIES = ("P0", "P1", "P2", "P3")
PERMISSION_FLAGS = ("paid_api", "publish", "external_messages", "cloud_resources", "main_push", "auto_merge")
ARTIFACT_KINDS = ("issue", "pr", "commit", "file", "url")
MAX_LIST = 50
MAX_TEXT = 300

FIELDS = ("schema_version", "project_id", "product_version", "spec_revision", "spec_url", "spec_approved",
          "issue_id", "task_id", "run_id", "owner_lane", "priority", "depends", "files_scope",
          "input_artifact_refs", "acceptance_criteria", "test_commands", "permission_flags", "budget_cap_usd",
          "requested_at")

_PROJECT = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
_VERSION = re.compile(r"^v\d{1,3}(\.\d{1,3}){0,2}$")
_REVISION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")
_SPEC = re.compile(r"^https://github\.com/Pavlovskyi-Andrii/blackboxlab-factoryos/(issues|pull)/\d{1,6}"
                   r"(#issuecomment-\d{1,12})?$")
_TASK = re.compile(r"^[A-Z]{1,6}-\d{1,6}$")
_RUN = re.compile(r"^run-[0-9a-f]{8,32}$")
_DEP = re.compile(r"^#?(\d{1,6})$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


@dataclass
class Result:
    ok: bool
    request: Optional[dict] = None
    reasons: list = field(default_factory=list)

    @property
    def codes(self) -> list:
        return [r["code"] for r in self.reasons]


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _path_problem(path: Any) -> Optional[str]:
    """Reason code for an unacceptable files_scope / artifact path, or None."""
    if not isinstance(path, str) or not path.strip() or len(path) > 200:
        return "bad_path"
    p = path.strip()
    if p.startswith("/") or re.match(r"^[A-Za-z]:", p) or "\\" in p:
        return "bad_path"
    parts = p.split("/")
    if any(part in ("", ".", "..") for part in parts) and p not in (".",):
        return "bad_path"
    if p in (".", "*", "**") or (len(parts) == 1 and "*" in p) or parts[0] in ("*", "**"):
        return "wildcard_root_scope"
    if parts[0] == ".git":
        return "bad_path"
    if any(part == ".env" or part.startswith(".env.") for part in parts):
        return "secret_path"
    return None


def validate(raw: Any, *, expected_lane: str = BUILDER_LANE) -> Result:
    """Check a raw build_request. Returns every problem, never raises on bad input."""
    reasons: list = []

    def bad(code: str, name: str) -> None:
        reasons.append({"code": code, "field": name})

    if not isinstance(raw, dict):
        return Result(False, None, [{"code": "not_an_object", "field": ""}])
    for key in sorted(set(raw) - set(FIELDS)):
        bad("unknown_field", key)

    if raw.get("schema_version") != SCHEMA_VERSION:
        bad("unknown_schema_version", "schema_version")

    project = _text(raw.get("project_id"))
    if not _PROJECT.match(project):
        bad("bad_project_id", "project_id")
    version = _text(raw.get("product_version")).lower()
    if not _VERSION.match(version):
        bad("bad_product_version", "product_version")
    revision = _text(raw.get("spec_revision"))
    if not _REVISION.match(revision):
        bad("bad_spec_revision", "spec_revision")

    spec = _text(raw.get("spec_url"))
    if not spec:
        bad("missing_owner_spec", "spec_url")
    elif not _SPEC.match(spec):
        bad("bad_spec_link", "spec_url")
    if raw.get("spec_approved") is not True:
        bad("spec_not_owner_approved", "spec_approved")

    issue = raw.get("issue_id")
    if not (isinstance(issue, int) and not isinstance(issue, bool) and 0 < issue < 1_000_000):
        bad("bad_issue_id", "issue_id")
    task = _text(raw.get("task_id"))
    if not _TASK.match(task):
        bad("bad_task_id", "task_id")
    run = raw.get("run_id")
    if run is not None and not (isinstance(run, str) and _RUN.match(run)):
        bad("bad_run_id", "run_id")

    lane = _text(raw.get("owner_lane")).lower()
    if lane not in LANES:
        bad("unknown_owner_lane", "owner_lane")
    elif lane != expected_lane:
        bad("wrong_owner_lane", "owner_lane")
    priority = _text(raw.get("priority")).upper()
    if priority not in PRIORITIES:
        bad("bad_priority", "priority")

    depends: list = []
    deps_raw = raw.get("depends", [])
    if not isinstance(deps_raw, list) or len(deps_raw) > MAX_LIST:
        bad("bad_depends", "depends")
    else:
        for d in deps_raw:
            m = _DEP.match(str(d).strip()) if isinstance(d, (str, int)) and not isinstance(d, bool) else None
            if not m:
                bad("bad_depends", "depends")
                break
            depends.append(int(m.group(1)))
        if issue in depends:
            bad("self_dependency", "depends")
    depends = sorted(set(depends))

    scope: list = []
    scope_raw = raw.get("files_scope")
    if not isinstance(scope_raw, list) or not scope_raw:
        bad("missing_files_scope", "files_scope")
    elif len(scope_raw) > MAX_LIST:
        bad("files_scope_too_large", "files_scope")
    else:
        for path in scope_raw:
            problem = _path_problem(path)
            if problem:
                bad(problem, "files_scope")
            else:
                scope.append(path.strip())
    scope = sorted(set(scope))

    artifacts: list = []
    arts_raw = raw.get("input_artifact_refs", [])
    if not isinstance(arts_raw, list) or len(arts_raw) > MAX_LIST:
        bad("bad_artifact_ref", "input_artifact_refs")
    else:
        for a in arts_raw:
            kind = a.get("kind") if isinstance(a, dict) else None
            ref = a.get("ref") if isinstance(a, dict) else None
            ok = (kind in ("issue", "pr") and isinstance(ref, int) and not isinstance(ref, bool) and ref > 0) or \
                 (kind == "commit" and isinstance(ref, str) and bool(_SHA.match(ref))) or \
                 (kind == "file" and _path_problem(ref) is None) or \
                 (kind == "url" and isinstance(ref, str) and ref.startswith("https://") and len(ref) <= 300
                  and not re.search(r"\s", ref))
            if not ok or set(a) - {"kind", "ref"}:
                bad("bad_artifact_ref", "input_artifact_refs")
            else:
                artifacts.append({"kind": kind, "ref": ref.strip() if isinstance(ref, str) else ref})
    artifacts.sort(key=lambda x: (x["kind"], str(x["ref"])))

    def text_list(name: str, missing: str) -> list:
        value = raw.get(name)
        if not isinstance(value, list) or not value:
            bad(missing, name)
            return []
        out = []
        for item in value[:MAX_LIST + 1]:
            t = _text(item)
            if not t or len(t) > MAX_TEXT or "\n" in t or "\r" in t:
                bad("bad_" + name, name)
                return []
            out.append(t)
        if len(value) > MAX_LIST:
            bad("bad_" + name, name)
        return out

    acceptance = text_list("acceptance_criteria", "missing_acceptance")
    commands = text_list("test_commands", "missing_test_commands")
    if any("`" in c or "$(" in c for c in commands):
        bad("bad_test_commands", "test_commands")

    flags_raw = raw.get("permission_flags")
    flags = {k: False for k in PERMISSION_FLAGS}
    if not isinstance(flags_raw, dict):
        bad("missing_permission_flags", "permission_flags")
    else:
        for key in sorted(flags_raw):
            if key not in PERMISSION_FLAGS:
                bad("unknown_permission_flag", "permission_flags." + key)
            elif flags_raw[key] is not False:
                bad("permission_not_allowed", "permission_flags." + key)   # zero-spend, no publishing
        for key in PERMISSION_FLAGS:
            if key not in flags_raw:
                bad("missing_permission_flag", "permission_flags." + key)

    budget = raw.get("budget_cap_usd")
    if isinstance(budget, bool) or not isinstance(budget, (int, float)) or budget != 0:
        bad("budget_not_zero", "budget_cap_usd")

    stamp = _text(raw.get("requested_at"))
    try:
        if not _STAMP.match(stamp):
            raise ValueError
        datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        bad("bad_requested_at", "requested_at")

    if reasons:
        return Result(False, None, reasons)
    request = {"schema_version": SCHEMA_VERSION, "project_id": project, "product_version": version,
               "spec_revision": revision, "spec_url": spec, "spec_approved": True, "issue_id": issue,
               "task_id": task, "run_id": run, "owner_lane": lane, "priority": priority, "depends": depends,
               "files_scope": scope, "input_artifact_refs": artifacts, "acceptance_criteria": acceptance,
               "test_commands": commands, "permission_flags": flags, "budget_cap_usd": 0,
               "requested_at": stamp}
    return Result(True, request, [])


def to_json(request: dict) -> str:
    """Stable serialisation: sorted keys, no spaces, UTF-8 kept."""
    return json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def from_json(text: str, *, expected_lane: str = BUILDER_LANE) -> Result:
    """Parse and re-validate; a stored request is never trusted blindly."""
    try:
        raw = json.loads(text)
    except (TypeError, ValueError):
        return Result(False, None, [{"code": "bad_json", "field": ""}])
    return validate(raw, expected_lane=expected_lane)
