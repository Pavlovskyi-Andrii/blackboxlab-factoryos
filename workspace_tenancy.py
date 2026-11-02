"""T-553 — Workspace data tenancy.

Jobs are the tenancy root: `job_workspaces(job_id, workspace_key)` assigns each production job to a
workspace (a missing row means the legacy `default` workspace). Artifacts, approvals, content
packages, publishing queue items, performance snapshots/attribution and Media Finisher/media jobs
inherit the workspace of their `job_id`; integration bindings already carry `workspace_key`.

Identities:
  * owner  — admin; unscoped (sees every workspace) for owner observability; writes default bindings.
  * viewer — the owner's read-only guest/auditor; unscoped read-only, as before T-553.
  * member — a customer user from FACTORY_WORKSPACE_MEMBERS; read/write limited to one workspace
             and to the tenant-aware route allowlist below. Everything else is operator-only.

The active scope lives in a ContextVar: None = unscoped admin/background, otherwise the workspace key.
Background work started from a member request inherits its scope; system loops set it explicitly
per row with `workspace_scope(...)`.
"""
import contextvars
import re
from contextlib import contextmanager

DEFAULT_WORKSPACE = "default"
_WORKSPACE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
_current = contextvars.ContextVar("factoryos_workspace", default=None)


def normalize_workspace(value):
    key = str(value or "").strip().lower()
    if not _WORKSPACE_RE.fullmatch(key):
        raise ValueError("workspace key must be 1-48 chars of a-z, 0-9, '-' or '_'")
    return key


def parse_members(raw):
    """FACTORY_WORKSPACE_MEMBERS="alice@x.com=acme,bob@y.com=globex" -> {email: workspace}. Bad entries are skipped."""
    members = {}
    for part in str(raw or "").split(","):
        email, sep, workspace = part.partition("=")
        email = email.strip().lower()
        if not sep or "@" not in email:
            continue
        try:
            members[email] = normalize_workspace(workspace)
        except ValueError:
            continue
    return members


def identity_workspace(identity):
    """Scope for a request identity: None (all workspaces) for owner/viewer, the bound key for members."""
    identity = identity or {}
    if identity.get("role") == "member":
        return normalize_workspace(identity.get("workspace"))
    return None


def current():
    return _current.get()


def binding_workspace():
    """Workspace whose bindings/credentials an action uses: the scoped one, or default for admin/system."""
    return _current.get() or DEFAULT_WORKSPACE


def visible(workspace_key):
    scope = _current.get()
    return scope is None or (workspace_key or DEFAULT_WORKSPACE) == scope


@contextmanager
def workspace_scope(workspace_key):
    token = _current.set(normalize_workspace(workspace_key) if workspace_key is not None else None)
    try:
        yield
    finally:
        _current.reset(token)


def set_scope(workspace_key):
    return _current.set(workspace_key)


def reset_scope(token):
    _current.reset(token)


JOB_WORKSPACE_SQL = "COALESCE((SELECT workspace_key FROM job_workspaces w WHERE w.job_id={col}),'default')"


def sql_filter(col="job_id"):
    """(" AND …", params) restricting rows whose `col` is a job id to the active scope; empty when unscoped."""
    scope = _current.get()
    if scope is None:
        return "", []
    return f" AND {JOB_WORKSPACE_SQL.format(col=col)}=?", [scope]


# Routes a member may call. Each id in the path is additionally ownership-checked below.
MEMBER_ROUTES = [
    ("GET", r"/(en|uk|ru)?"),
    ("GET", r"/api/(status|version|workspace|approval|publishing|performance|integrations|oauth/providers)"),
    ("POST", r"/api/jobs"),
    ("GET|POST", r"/api/jobs/[^/]+(/.*)?"),
    ("POST", r"/api/publishing/[^/]+/(schedule|publish|dry-run|confirm|refresh)"),
    ("POST", r"/api/publishing/run-due"),
    ("GET", r"/api/performance/[^/]+"),
    ("POST", r"/api/performance/(snapshots|[^/]+/sync)"),
    ("POST", r"/api/integrations/([^/]+/(connect|disconnect|switch)|disconnect-all)"),
    ("POST", r"/api/oauth/[^/]+/(authorize|disconnect)"),
    ("GET", r"/api/artifacts/[^/]+/media"),
    ("GET", r"/api/handoffs/[^/]+/[^/]+"),
    ("GET", r"/api/browser-runs/[^/]+"),
    ("GET", r"/api/media-finisher/[^/]+"),
    ("POST", r"/logout"),
]

# Job sub-routes that touch shared operator data (global Content Brain ideas, agent internals).
MEMBER_DENY = [
    r"/api/jobs/[^/]+/idea-link/.*",
]

# (path regex, resource kind, group holding the id). Ids that are not route words are ownership-checked.
RESOURCE_ROUTES = [
    (r"/api/jobs/([^/]+)(/.*)?", "job"),
    (r"/api/publishing/([^/]+)/.+", "publish"),
    (r"/api/performance/([^/]+)(/sync)?", "publish"),
    (r"/api/artifacts/([^/]+)(/.*)?", "artifact"),
    (r"/api/handoffs/[^/]+/([^/]+)", "artifact"),
    (r"/api/browser-runs/([^/]+)", "artifact"),
    (r"/api/media-finisher/([^/]+)(/.*)?", "edit_job"),
    (r"/api/media-jobs/([^/]+)(/.*)?", "media_job"),
]
_ROUTE_WORDS = {"run-due", "snapshots", "profiles"}

_RESOURCE_JOB_SQL = {
    "job": "SELECT id AS job_id FROM jobs WHERE id=?",
    "publish": "SELECT job_id FROM publishing_queue WHERE id=?",
    "artifact": "SELECT job_id FROM artifacts WHERE id=?",
    "edit_job": "SELECT production_job_id AS job_id FROM edit_jobs WHERE id=?",
    "media_job": "SELECT job_id FROM media_jobs WHERE id=?",
}


def member_route_allowed(method, path):
    method = method.upper()
    if method in ("HEAD", "OPTIONS"):
        method = "GET"
    if any(re.fullmatch(pattern, path) for pattern in MEMBER_DENY):
        return False
    return any(method in methods.split("|") and re.fullmatch(pattern, path) for methods, pattern in MEMBER_ROUTES)


def path_resources(path):
    out = []
    for pattern, kind in RESOURCE_ROUTES:
        m = re.fullmatch(pattern, path)
        if m and m.group(1) not in _ROUTE_WORDS:
            out.append((kind, m.group(1)))
    return out


def job_workspace(con, job_id):
    if not job_id:
        return None
    row = con.execute("SELECT workspace_key FROM job_workspaces WHERE job_id=?", (job_id,)).fetchone()
    return row[0] if row else DEFAULT_WORKSPACE


def resource_workspace(con, kind, resource_id):
    """Workspace owning a resource, or None when it does not exist / has no owning job (operator-only)."""
    row = con.execute(_RESOURCE_JOB_SQL[kind], (resource_id,)).fetchone()
    if not row or not row[0]:
        return None
    return job_workspace(con, row[0])
