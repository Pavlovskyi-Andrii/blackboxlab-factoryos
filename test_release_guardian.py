"""T-616 / #189 AI Release Guardian: classification fixtures, read-only client, cache, rate limit, owner-only route.

Offline: every GitHub response is a fixture. Run: python test_release_guardian.py
"""
import os
import unittest
import urllib.error

from release_guardian import (GitHubReader, GitHubUnavailable, ReleaseGuardian, assess_pull, classify_readiness,
                              classify_run, collect_checks, parse_pr_numbers, parse_rules, summarize_reviews)

REPO = "Pavlovskyi-Andrii/blackboxlab-factoryos"
SHA = "133de10a82d59d39acfc1eba68b85df022630350"


def run(name, status="completed", conclusion="success", rid=1, app="github-actions", suite=10):
    return {"id": rid, "name": name, "status": status, "conclusion": conclusion, "app": {"slug": app},
            "html_url": f"https://github.com/{REPO}/runs/{rid}", "check_suite": {"id": suite}}


def suite(sid, status="completed", conclusion="success", runs=1, app="github-actions"):
    return {"id": sid, "status": status, "conclusion": conclusion, "latest_check_runs_count": runs, "app": {"slug": app}}


def readiness(runs=(), **kw):
    checks, _ = collect_checks(runs, suites=kw.pop("suites", ()), workflow_runs=kw.pop("workflow_runs", ()),
                               statuses=kw.pop("statuses", ()))
    return classify_readiness(checks, **kw)


def codes(result):
    return [r["code"] for r in result["reasons"]]


class ClassifyRunTest(unittest.TestCase):
    def test_only_success_passes(self):
        self.assertEqual(classify_run("completed", "success"), "passed")
        for c in ("failure", "timed_out", "action_required", "startup_failure", "cancelled"):
            self.assertEqual(classify_run("completed", c), "failed", c)
        for c in ("skipped", "neutral", "stale", "", None, "something_new"):
            self.assertEqual(classify_run("completed", c), "not_verified", c)
        for s in ("queued", "in_progress", "waiting", "requested", "pending"):
            self.assertEqual(classify_run(s, None), "pending", s)
        self.assertEqual(classify_run("weird_status", None), "not_verified")


class ReadinessTest(unittest.TestCase):
    def test_all_success_is_green(self):
        r = readiness([run("smoke", rid=1), run("ui", rid=2)], required=[])
        self.assertEqual(r["readiness"], "green")
        self.assertEqual(r["counts"], {"passed": 2, "failed": 0, "pending": 0, "not_verified": 0})

    def test_no_checks_is_unknown_never_green(self):
        r = readiness([], required=[])
        self.assertEqual(r["readiness"], "unknown")
        self.assertIn("no_checks", codes(r))

    def test_only_skipped_is_unknown(self):
        r = readiness([run("smoke", conclusion="skipped", rid=1)], required=[])
        self.assertEqual(r["readiness"], "unknown")
        self.assertIn("nothing_passed", codes(r))
        self.assertIn("not_counted", codes(r))

    def test_only_neutral_is_unknown(self):
        r = readiness([run("lint", conclusion="neutral", rid=1), run("x", conclusion="stale", rid=2)], required=[])
        self.assertEqual(r["readiness"], "unknown")
        self.assertEqual(r["counts"]["passed"], 0)

    def test_skipped_beside_success_is_listed_not_counted(self):
        r = readiness([run("smoke", rid=1), run("deploy", conclusion="skipped", rid=2)], required=[])
        self.assertEqual(r["readiness"], "green")
        self.assertEqual(r["counts"]["passed"], 1)
        self.assertIn({"code": "not_counted", "name": "deploy", "detail": "skipped"}, r["reasons"])

    def test_cancelled_is_red(self):
        r = readiness([run("smoke", rid=1), run("ui", conclusion="cancelled", rid=2)], required=[])
        self.assertEqual(r["readiness"], "red")
        self.assertIn("check_failed", codes(r))

    def test_failure_beats_pending(self):
        r = readiness([run("a", conclusion="failure", rid=1), run("b", status="in_progress", conclusion=None, rid=2)],
                      required=[])
        self.assertEqual(r["readiness"], "red")

    def test_pending(self):
        r = readiness([run("a", rid=1), run("b", status="queued", conclusion=None, rid=2)], required=[])
        self.assertEqual(r["readiness"], "pending")

    def test_required_but_missing_is_unknown(self):
        r = readiness([run("ui", rid=1)], required=["syntax-and-smoke"])
        self.assertEqual(r["readiness"], "unknown")
        self.assertIn({"code": "required_missing", "name": "syntax-and-smoke"}, r["reasons"])

    def test_required_but_skipped_is_unknown(self):
        r = readiness([run("ui", rid=1), run("syntax-and-smoke", conclusion="skipped", rid=2)],
                      required=["syntax-and-smoke"])
        self.assertEqual(r["readiness"], "unknown")
        self.assertIn({"code": "required_not_verified", "name": "syntax-and-smoke"}, r["reasons"])

    def test_required_present_and_passed_is_green(self):
        r = readiness([run("syntax-and-smoke", rid=1)], required=["syntax-and-smoke"])
        self.assertEqual(r["readiness"], "green")

    def test_required_missing_while_other_pending_stays_pending(self):
        r = readiness([run("ui", status="in_progress", conclusion=None, rid=1)], required=["smoke"])
        self.assertEqual(r["readiness"], "pending")
        self.assertIn("required_missing", codes(r))

    def test_unreadable_rules_are_said_not_assumed(self):
        r = readiness([run("a", rid=1)], required=None)
        self.assertEqual(r["readiness"], "green")
        self.assertIn("required_unknown", codes(r))

    def test_truncated_list_cannot_be_green(self):
        r = readiness([run("a", rid=1)], required=[], truncated=True)
        self.assertEqual(r["readiness"], "unknown")
        self.assertIn("list_truncated", codes(r))

    def test_github_unavailable_is_unknown(self):
        r = classify_readiness([], required=[], available=False)
        self.assertEqual((r["readiness"], codes(r)), ("unknown", ["github_unavailable"]))

    def test_rerun_replaces_earlier_failure(self):
        r = readiness([run("smoke", conclusion="failure", rid=1), run("smoke", conclusion="success", rid=5)], required=[])
        self.assertEqual(r["readiness"], "green")
        r = readiness([run("smoke", conclusion="success", rid=5), run("smoke", conclusion="failure", rid=9)], required=[])
        self.assertEqual(r["readiness"], "red")

    def test_workflow_without_jobs_is_red_even_beside_green_checks(self):
        # Recorded from PR #162: three green runs came from a workflow_dispatch run, while the pull_request run of
        # "FactoryOS CI" finished `failure` without running one job. GitHub's list of runs alone looks green.
        runs = [run("syntax-and-smoke", rid=1, suite=916), run("ec2-python39-import", rid=2, suite=916),
                run("ui-screenshots", rid=3, suite=916)]
        suites = [suite(851, status="queued", conclusion=None, runs=0, app="render"), suite(916, runs=3),
                  suite(540, conclusion="failure", runs=0)]
        wruns = [{"id": 722, "name": "FactoryOS CI", "event": "pull_request", "check_suite_id": 540,
                  "html_url": f"https://github.com/{REPO}/actions/runs/722"},
                 {"id": 553, "name": "FactoryOS CI", "event": "workflow_dispatch", "check_suite_id": 916}]
        checks, notes = collect_checks(runs, suites=suites, workflow_runs=wruns)
        r = classify_readiness(checks, required=[])
        self.assertEqual(r["readiness"], "red")
        self.assertIn({"code": "workflow_no_jobs", "name": "FactoryOS CI (pull_request)", "detail": "failure"}, r["reasons"])
        self.assertEqual(notes, [{"code": "app_suite_without_runs", "name": "render", "detail": "queued"}])

    def test_queued_workflow_without_jobs_is_pending(self):
        r = readiness([run("a", rid=1)], suites=[suite(7, status="queued", conclusion=None, runs=0)], required=[])
        self.assertEqual(r["readiness"], "pending")

    def test_successful_workflow_without_jobs_is_not_a_pass(self):
        checks, notes = collect_checks([], suites=[suite(7, conclusion="success", runs=0)])
        self.assertEqual(checks, [])
        self.assertEqual(notes[0]["code"], "workflow_without_jobs")
        self.assertEqual(classify_readiness(checks, required=[])["readiness"], "unknown")

    def test_other_app_suite_never_blocks_or_passes(self):
        r = readiness([], suites=[suite(1, status="queued", conclusion=None, runs=0, app="render")], required=[])
        self.assertEqual(r["readiness"], "unknown")

    def test_commit_statuses(self):
        ok = {"id": 1, "context": "render", "state": "success"}
        self.assertEqual(readiness([], statuses=[ok], required=[])["readiness"], "green")
        self.assertEqual(readiness([], statuses=[dict(ok, state="error")], required=[])["readiness"], "red")
        self.assertEqual(readiness([], statuses=[dict(ok, state="pending")], required=[])["readiness"], "pending")
        # the newest status per context wins
        self.assertEqual(readiness([], statuses=[dict(ok, id=1, state="failure"), dict(ok, id=2)], required=[])["readiness"], "green")


class ReviewsRulesVerdictTest(unittest.TestCase):
    def test_latest_decisive_review_per_reviewer(self):
        reviews = [{"id": 1, "user": {"login": "a"}, "state": "CHANGES_REQUESTED"},
                   {"id": 2, "user": {"login": "a"}, "state": "APPROVED"},
                   {"id": 3, "user": {"login": "a"}, "state": "COMMENTED"},
                   {"id": 4, "user": {"login": "b"}, "state": "CHANGES_REQUESTED"}]
        s = summarize_reviews(reviews, [{"login": "c"}])
        self.assertEqual(s, {"approved": ["a"], "changes_requested": ["b"], "requested": ["c"]})

    def test_parse_rules(self):
        self.assertEqual(parse_rules(None), {"required_checks": None, "required_approvals": None, "visible": False})
        self.assertEqual(parse_rules([]), {"required_checks": [], "required_approvals": 0, "visible": True})
        rules = [{"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": "smoke"}]}},
                 {"type": "pull_request", "parameters": {"required_approving_review_count": 1}}]
        self.assertEqual(parse_rules(rules), {"required_checks": ["smoke"], "required_approvals": 1, "visible": True})

    def verdict(self, pull=None, ready="green", reviews=None, rules=None):
        return assess_pull(dict({"state": "open", "draft": False, "mergeable": True, "mergeable_state": "clean"}, **(pull or {})),
                           readiness={"readiness": ready}, reviews=reviews or summarize_reviews([]),
                           rules=rules or {"required_checks": [], "required_approvals": 0})

    def test_ready_only_when_green_and_unblocked(self):
        self.assertEqual(self.verdict()["verdict"], "ready")
        for ready in ("red", "pending", "unknown"):
            v = self.verdict(ready=ready)
            self.assertEqual(v["verdict"], "not_ready")
            self.assertIn({"code": "checks_" + ready}, v["blockers"])

    def test_pr_blockers(self):
        self.assertIn({"code": "draft"}, self.verdict({"draft": True})["blockers"])
        self.assertIn({"code": "merge_conflict"}, self.verdict({"mergeable": False, "mergeable_state": "dirty"})["blockers"])
        self.assertIn({"code": "mergeability_unknown"}, self.verdict({"mergeable": None})["notes"])
        v = self.verdict(reviews={"approved": [], "changes_requested": ["b"], "requested": []})
        self.assertEqual(v["verdict"], "not_ready")
        v = self.verdict(rules={"required_checks": [], "required_approvals": 1})
        self.assertIn({"code": "approvals_missing", "detail": "0/1"}, v["blockers"])
        self.assertIn({"code": "review_rules_unknown"},
                      self.verdict(rules={"required_checks": None, "required_approvals": None})["notes"])

    def test_closed_and_merged(self):
        self.assertEqual(self.verdict({"state": "closed", "merged": True})["verdict"], "merged")
        self.assertEqual(self.verdict({"state": "closed"})["verdict"], "closed")

    def test_parse_pr_numbers(self):
        self.assertEqual(parse_pr_numbers("#162, 163;144 x -1 0"), [162, 163, 144])
        self.assertEqual(len(parse_pr_numbers(",".join(str(i) for i in range(1, 40)))), 10)


class FakeGitHub:
    """A fixture GitHub. Records every (path, token) and refuses anything but the expected read paths."""

    def __init__(self, routes, headers=None):
        self.routes = routes
        self.headers = headers or {"X-RateLimit-Remaining": "4000", "X-RateLimit-Reset": "9999999999"}
        self.calls = []

    def __call__(self, path, token):
        self.calls.append((path, token))
        for prefix, value in self.routes.items():
            if path.startswith(prefix):
                if isinstance(value, Exception):
                    raise value
                return value, self.headers
        raise urllib.error.HTTPError("https://api.github.com/x", 404, "Not Found", {}, None)


def pr_routes(number=7, sha=SHA, runs=None, rules=None, reviews=None, pull=None):
    return {
        f"/pulls/{number}/reviews": reviews if reviews is not None else [],
        f"/pulls/{number}": dict({"number": number, "title": "T-616 test", "state": "open", "draft": False, "mergeable": True,
                                  "mergeable_state": "clean", "user": {"login": "claude", "type": "User"},
                                  "head": {"sha": sha}, "base": {"ref": "main"}, "requested_reviewers": []}, **(pull or {})),
        "/rules/branches/main": rules if rules is not None else [],
        f"/commits/{sha}/check-runs": {"total_count": len(runs or []), "check_runs": runs or []},
        f"/commits/{sha}/check-suites": {"check_suites": []},
        f"/actions/runs?head_sha={sha}": {"workflow_runs": []},
        f"/commits/{sha}/status": {"state": "pending", "total_count": 0, "statuses": []},
        "/pulls?state=open": [{"number": number}],
    }


class ClientTest(unittest.TestCase):
    def setUp(self):
        self.t = [1000.0]

    def guardian(self, fake, token="tok-SECRET-123"):
        return ReleaseGuardian(GitHubReader(REPO, lambda: token, fetch=fake, clock=lambda: self.t[0], ttl=120))

    def test_end_to_end_green_pr(self):
        fake = FakeGitHub(pr_routes(runs=[run("smoke", rid=1)]))
        d = self.guardian(fake).dashboard([7])
        p = d["pulls"][0]
        self.assertEqual((p["readiness"]["readiness"], p["verdict"], p["author"]["login"]), ("green", "ready", "claude"))
        self.assertEqual(d["auth"], "token")
        self.assertNotIn("SECRET", repr(d))

    def test_combined_status_pending_without_statuses_is_not_pending(self):
        # /status says "pending" with zero statuses; that alone must not make a PR pending, nor green.
        d = self.guardian(FakeGitHub(pr_routes(runs=[]))).dashboard([7])
        self.assertEqual(d["pulls"][0]["readiness"]["readiness"], "unknown")
        self.assertEqual(d["pulls"][0]["verdict"], "not_ready")

    def test_only_get_paths_and_no_writes(self):
        fake = FakeGitHub(pr_routes(runs=[run("smoke", rid=1)]))
        self.guardian(fake).dashboard(None)
        for path, _ in fake.calls:
            self.assertFalse(any(w in path for w in ("/merge", "/comments", "/statuses/", "/approve", "/dispatches")), path)

    def test_default_http_get_is_get_only(self):
        import inspect
        import release_guardian
        src = inspect.getsource(release_guardian)
        self.assertIn('method="GET"', src)
        for verb in ('method="POST"', 'method="PUT"', 'method="PATCH"', 'method="DELETE"'):
            self.assertNotIn(verb, src)

    def test_cache_ttl(self):
        fake = FakeGitHub(pr_routes(runs=[run("smoke", rid=1)]))
        g = self.guardian(fake)
        g.dashboard([7])
        n = len(fake.calls)
        g.dashboard([7])
        self.assertEqual(len(fake.calls), n)  # served from cache
        self.t[0] += 121
        g.dashboard([7])
        self.assertEqual(len(fake.calls), 2 * n)

    def test_github_down_is_unknown(self):
        err = urllib.error.URLError("down")
        fake = FakeGitHub({"/": err})
        d = self.guardian(fake).dashboard([7])
        p = d["pulls"][0]
        self.assertEqual((p["available"], p["readiness"]["readiness"], p["verdict"]), (False, "unknown", "unknown"))

    def test_checks_down_after_pull_is_unknown(self):
        routes = pr_routes(runs=[run("smoke", rid=1)])
        routes[f"/commits/{SHA}/check-runs"] = urllib.error.URLError("down")
        p = self.guardian(FakeGitHub(routes)).dashboard([7])["pulls"][0]
        self.assertEqual(p["readiness"]["readiness"], "unknown")
        self.assertEqual(p["readiness"]["reasons"][0]["code"], "github_unavailable")

    def test_stale_cache_served_on_failure(self):
        routes = pr_routes(runs=[run("smoke", rid=1)])
        fake = FakeGitHub(routes)
        g = self.guardian(fake)
        g.dashboard([7])
        self.t[0] += 500
        for k in list(routes):
            routes[k] = urllib.error.URLError("down")
        p = g.dashboard([7])["pulls"][0]
        self.assertEqual(p["readiness"]["readiness"], "green")

    def test_rate_limit_guard_stops_calls(self):
        fake = FakeGitHub(pr_routes(runs=[run("smoke", rid=1)]),
                          headers={"X-RateLimit-Remaining": "2", "X-RateLimit-Reset": "99999"})
        reader = GitHubReader(REPO, lambda: "", fetch=fake, clock=lambda: self.t[0])
        reader.get("/pulls/7")
        with self.assertRaises(GitHubUnavailable) as ctx:
            reader.get("/pulls/8")
        self.assertEqual(ctx.exception.reason, "rate_limit_guard")
        self.assertEqual(len(fake.calls), 1)

    def test_anonymous_mode_caps_prs(self):
        routes = pr_routes(runs=[run("smoke", rid=1)])
        routes["/pulls?state=open"] = [{"number": i} for i in range(1, 30)]
        fake = FakeGitHub(routes)
        d = self.guardian(fake, token="").dashboard(None)
        self.assertEqual((d["auth"], d["limit"], len(d["pulls"])), ("anonymous", 5, 5))
        self.assertTrue(all(tok == "" for _, tok in fake.calls))

    def test_required_check_from_rules(self):
        rules = [{"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": "syntax-and-smoke"}]}}]
        p = self.guardian(FakeGitHub(pr_routes(runs=[run("ui", rid=1)], rules=rules))).dashboard([7])["pulls"][0]
        self.assertEqual(p["readiness"]["readiness"], "unknown")
        self.assertEqual(p["required_checks"], ["syntax-and-smoke"])

    def test_rules_unreadable(self):
        routes = pr_routes(runs=[run("smoke", rid=1)])
        del routes["/rules/branches/main"]
        p = self.guardian(FakeGitHub(routes)).dashboard([7])["pulls"][0]
        self.assertIsNone(p["required_checks"])
        self.assertIn({"code": "review_rules_unknown"}, p["notes"])

    def test_error_reason_hides_token(self):
        err = urllib.error.HTTPError("https://api.github.com/x", 401, "Bad credentials tok-SECRET-123", {}, None)
        d = self.guardian(FakeGitHub({"/": err})).dashboard([7])
        self.assertNotIn("SECRET", repr(d))
        self.assertEqual(d["pulls"][0]["reason"], "invalid_token")


class RouteTest(unittest.TestCase):
    def test_owner_only(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from release_guardian import install_release_guardian_routes
        fake = FakeGitHub(pr_routes(runs=[run("smoke", rid=1)]))
        g = ReleaseGuardian(GitHubReader(REPO, lambda: "", fetch=fake))
        app = FastAPI()
        role = {"v": None}
        install_release_guardian_routes(app, g, lambda r: {"role": role["v"]} if role["v"] else None)
        c = TestClient(app)
        for r in (None, "viewer", "member"):
            role["v"] = r
            self.assertEqual(c.get("/api/release-guardian?prs=7").status_code, 403, r)
        self.assertEqual(fake.calls, [])  # refused requests never reach GitHub
        role["v"] = "owner"
        res = c.get("/api/release-guardian?prs=7")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["pulls"][0]["number"], 7)
        self.assertTrue(res.json()["read_only"])
        self.assertEqual(c.post("/api/release-guardian").status_code, 405)

    def test_app_wiring_requires_login(self):
        """Through the real app and its auth middleware, with login enabled. No request here reaches GitHub."""
        os.environ.setdefault("DATA_DIR", "/tmp/factoryos-release-guardian-test")
        from unittest.mock import patch
        import app as factory_app
        from fastapi.testclient import TestClient
        paths = {getattr(r, "path", "") for r in factory_app.app.routes}
        self.assertIn("/api/release-guardian", paths)
        with patch.object(factory_app, "FACTORY_PASSWORD", "auth-enabled-for-tests"):
            c = TestClient(factory_app.app)
            self.assertEqual(c.get("/api/release-guardian?prs=1").status_code, 401)
            viewer = factory_app._role_session_token("viewer", "guest")
            c.cookies.set(factory_app.COOKIE_NAME, viewer)
            self.assertEqual(c.get("/api/release-guardian?prs=1").status_code, 403)

if __name__ == "__main__":
    unittest.main(verbosity=1)
