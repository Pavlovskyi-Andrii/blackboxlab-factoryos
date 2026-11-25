"""T-740 Ops relay: the fixed operation catalog, shared by the server (``ops_relay.py``) and the EC2 executor
(``autopilot/ops_agent.py``).

No dependencies (the executor runs as root under the EC2 host's Python 3.9). Nothing here runs a command: ``plan``
turns a validated request into argv lists, the executor runs them without a shell. Anything outside this catalog
cannot be expressed: ops, units and the two integers are checked against constants, there are no free-form strings.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Tuple

OPS_CLASS: Dict[str, str] = {
    "status": "read",
    "journal": "read",
    "host": "read",
    "restart": "restart",
    "sync_checkout": "install",
    "install_surfer_unit": "install",
}
CLASSES = ("read", "restart", "install")
DEFAULT_CLASSES = ("read", "restart")

SURFER_UNIT = "factoryos-surfer-worker.service"
CLAUDE_UNIT = "factoryos-claude-worker.service"
READ_UNITS = (
    SURFER_UNIT,
    CLAUDE_UNIT,
    "factoryos-runner-supervisor.service",
    "factoryos-runner-supervisor.timer",
    "factoryos-ops-agent.service",
    "factoryos-ops-agent.timer",
)
RESTART_UNITS = (SURFER_UNIT, CLAUDE_UNIT)
UNIT_OPS = ("status", "journal", "restart")

MAX_MINUTES = 180
MAX_LINES = 300
DEFAULT_MINUTES = 30
DEFAULT_LINES = 100
STATUS_JOURNAL_LINES = 20
OP_TIMEOUT_SECONDS = 60
MAX_OUTPUT_BYTES = 32 * 1024
WORKER_USER = "ec2-user"
DEFAULT_REPO = "/opt/factoryos"
# Root-owned copy made by deploy/install_ops_agent.sh (owner-run). Root only ever executes files from here, never from
# the ec2-user checkout above, whose content the worker user (and git) can change.
ROOT_LIB = "/usr/local/lib/factoryos-ops"


def _int(value, name: str, low: int, high: int, default: int) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"{name} must be an integer {low}..{high}")
    try:
        number = int(str(value).strip())
    except ValueError:
        raise ValueError(f"{name} must be an integer {low}..{high}")
    if not low <= number <= high:
        raise ValueError(f"{name} must be an integer {low}..{high}")
    return number


def validate(args: dict) -> dict:
    """The only request shapes that exist. Returns ``{op, unit, minutes, lines}`` (unused fields are None)."""
    if not isinstance(args, dict):
        raise ValueError("arguments must be an object")
    op = str(args.get("op") or "").strip()
    if op not in OPS_CLASS:
        raise ValueError("unknown op; allowed: " + ", ".join(OPS_CLASS))
    unit = args.get("unit")
    out = {"op": op, "unit": None, "minutes": None, "lines": None}
    if op in UNIT_OPS:
        unit = str(unit or "").strip()
        allowed = RESTART_UNITS if op == "restart" else READ_UNITS
        if unit not in allowed:
            raise ValueError(f"unit for {op} must be one of: " + ", ".join(allowed))
        out["unit"] = unit
    elif unit not in (None, ""):
        raise ValueError(f"{op} takes no unit")
    if op == "journal":
        out["minutes"] = _int(args.get("minutes"), "minutes", 1, MAX_MINUTES, DEFAULT_MINUTES)
        out["lines"] = _int(args.get("lines"), "lines", 1, MAX_LINES, DEFAULT_LINES)
    elif args.get("minutes") not in (None, "") or args.get("lines") not in (None, ""):
        raise ValueError(f"{op} takes no minutes / lines")
    return out


def classes_from(raw: Optional[str]) -> Tuple[str, ...]:
    """``FACTORY_OPS_RELAY_CLASSES``: comma list of read / restart / install; unset → read + restart.
    Set but naming no known class (e.g. ``none``) → nothing allowed (fail closed)."""
    if raw is None or not str(raw).strip():
        return DEFAULT_CLASSES
    wanted = {x.strip().lower() for x in str(raw).split(",")}
    return tuple(c for c in CLASSES if c in wanted)


# A step: (label, argv, run as the worker user?). The executor runs each with a shared deadline.
Step = Tuple[str, List[str], bool]


def plan(request: dict, repo: str = DEFAULT_REPO) -> List[Step]:
    """Validated request → fixed argv lists. Raises ValueError for anything not in the catalog."""
    req = validate(request)
    op, unit = req["op"], req["unit"]
    git = ["git", "-C", repo]
    if op == "status":
        return [
            ("state", ["systemctl", "show", unit, "--no-pager",
                       "-p", "ActiveState,SubState,Result,NRestarts,ActiveEnterTimestamp,ExecMainStatus,UnitFileState"],
             False),
            ("is-active", ["systemctl", "is-active", unit], False),
            ("journal", ["journalctl", "-u", unit, "-n", str(STATUS_JOURNAL_LINES), "--no-pager", "-o", "short-iso"],
             False),
        ]
    if op == "journal":
        return [("journal", ["journalctl", "-u", unit, "--since", f"-{req['minutes']}min", "-n", str(req["lines"]),
                             "--no-pager", "-o", "short-iso"], False)]
    if op == "host":
        return [
            ("memory", ["free", "-m"], False),
            ("disk", ["df", "-h", "/"], False),
            ("uptime", ["uptime"], False),
            ("chrome-processes", ["pgrep", "-c", "-f", "chrom"], False),
            ("branch", git + ["rev-parse", "--abbrev-ref", "HEAD"], True),
            ("head", git + ["rev-parse", "--short", "HEAD"], True),
            ("origin-main", git + ["rev-parse", "--short", "origin/main"], True),
            ("behind-origin-main", git + ["rev-list", "--count", "HEAD..origin/main"], True),
        ]
    if op == "restart":
        return [
            ("reset-failed", ["systemctl", "reset-failed", unit], False),
            ("restart", ["systemctl", "restart", "--no-block", unit], False),
            ("wait", ["sleep", "8"], False),
            ("state", ["systemctl", "show", unit, "--no-pager", "-p", "ActiveState,SubState,Result,NRestarts"], False),
        ]
    if op == "sync_checkout":
        return [
            ("before", git + ["rev-parse", "--short", "HEAD"], True),
            ("upstream", git + ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], True),
            ("fetch", git + ["fetch", "--quiet", "origin"], True),
            ("fast-forward", git + ["merge", "--ff-only", "@{u}"], True),
            ("after", git + ["rev-parse", "--short", "HEAD"], True),
        ]
    if op == "install_surfer_unit":
        # Re-applies the owner-installed copy of the Surfer unit (made by install_ops_agent.sh); a new unit version from
        # the checkout needs the owner to run install_ops_agent.sh again (root never runs checkout files).
        return [("install", ["env", "FACTORYOS_REPO=" + ROOT_LIB, "bash", ROOT_LIB + "/deploy/install_surfer_worker.sh"],
                 False)]
    raise ValueError("unknown op")  # pragma: no cover - validate() already refused it


# ---------------------------------------------------------------------------------------------------- redaction
_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S),
    re.compile(r"(?i)\b(authorization|proxy-authorization|cookie|set-cookie|x-api-key)(\s*[:=]\s*)[^\r\n]+"),
    re.compile(r"(?i)\b(bearer|basic|token)(\s+)[A-Za-z0-9._~+/=-]{12,}"),
    # KEY=value / KEY: value where the key names a credential (env dumps, config prints)
    re.compile(r"(?i)\b([A-Z0-9_.-]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY|PRIVATE_KEY|ACCESS_KEY|CREDENTIAL|"
               r"COOKIE|SESSION|AUTH)[A-Z0-9_.-]*)(\s*[:=]\s*['\"]?)[^\s'\",;]+"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]{12,})"),
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"),  # JWT
    re.compile(r"(?i)(https?://[^\s/:@]+:)[^\s/@]+(?=@)"),  # credentials inside a URL
    re.compile(r"(?i)([?&](?:key|token|access_token|sig|signature)=)[^&\s]+"),
)
MASK = "[redacted]"
MIN_KNOWN_SECRET = 8


def redact(text: str, known: Iterable[str] = ()) -> str:
    """Every known secret value literally, then credential-shaped text. Idempotent."""
    out = str(text or "")
    for secret in sorted({str(s) for s in known if s and len(str(s)) >= MIN_KNOWN_SECRET}, key=len, reverse=True):
        out = out.replace(secret, MASK)
    for pattern in _PATTERNS:
        def _sub(m, _p=pattern):
            groups = m.groups()
            if len(groups) >= 2 and groups[1] is not None and groups[0] is not None:
                return groups[0] + groups[1] + MASK
            if len(groups) == 1 and groups[0] is not None:
                return groups[0] + MASK
            return MASK
        out = pattern.sub(_sub, out)
    return out


def cap(text: str, limit: int = MAX_OUTPUT_BYTES) -> str:
    """At most ``limit`` UTF-8 bytes; keeps the tail (the newest journal lines) and says what was cut."""
    raw = str(text or "").encode("utf-8", "replace")
    if len(raw) <= limit:
        return str(text or "")
    note = f"[… {len(raw) - limit + 64} bytes cut …]\n".encode()
    tail = raw[-(limit - len(note)):]
    return (note + tail).decode("utf-8", "ignore")
