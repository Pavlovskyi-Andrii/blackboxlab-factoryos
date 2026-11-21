"""T-634 "Help us improve" quiz + analyst agent (#270, owner 2026-11-16: no human in the feedback loop).

A short, optional quiz at the bottom of an MVP page (first: MyCast). Answers go into the T-630 Product Evolution
ledger as consented, in-product feedback; an analyst pass after each answer looks for a theme that crossed the owner's
threshold and, when one did, writes a V2 proposal and hands it to Builder through one Relay ticket (standing rule).

Rules
- The quiz is optional and asks for consent; without `consent: true` nothing is stored.
- One answer per participant per quiz version: a signed-in listener counts once; an anonymous visitor is keyed by a
  per-day hash of the client address (never stored in clear). Per-client and global daily caps.
- Only signed-in listeners who actually used the product count toward a theme (`q_use` != "not_yet"): an anonymous
  identity rotates daily and cannot be a unique person for the threshold. Anonymous answers are kept as feedback.
- Threshold (owner default): at least MIN_PEOPLE unique people support the theme, at least MIN_SHARE of the version's
  sample, and contrary answers below half the support. Synthetic data never counts and never reaches Relay.
- Auto hand-off is on by default and has a kill switch (FACTORY_QUIZ_AUTO_V2=0): then proposals wait for the owner.
  Nothing here merges, deploys or publishes; a hand-off is a Relay task, the code still goes through PR + CI.
- Rewards and e-mails are recorded but held while their flags are off (FACTORY_QUIZ_REWARDS, FACTORY_QUIZ_MAIL):
  the gift terms and the mail provider are the owner's call (T-634-H). No gift is promised on the page while off.
- An e-mail is kept only with a separate contact consent, and the owner can delete a submission (with its e-mail).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import Request
from fastapi.responses import JSONResponse

from mvp_evolution import EvolutionError, EvolutionStore, clean_text

LANGS = ("uk", "ru", "en")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,180}\.[A-Za-z]{2,24}$")
PER_CLIENT_DAILY = 3
GLOBAL_DAILY = 500
MIN_ANSWERS = 3
FREE_TEXT_MAX = 500
REWARD_DAYS = 7
POLICY = "quiz-threshold"


def _t(uk: str, ru: str, en: str) -> dict[str, str]:
    return {"uk": uk, "ru": ru, "en": en}


# Themes the quiz can surface, with the V2 change the analyst proposes once a theme crosses the threshold.
THEMES: dict[str, dict[str, Any]] = {
    "shorter-episodes": {"title": _t("Коротші епізоди (5 хв)", "Короче эпизоды (5 мин)", "Shorter 5-minute episodes"),
                         "change": "Offer a 5-minute episode length in the configurator and generate to it",
                         "test": "A listener picks 5 minutes and the next episode is 4–6 minutes long"},
    "longer-episodes": {"title": _t("Довші епізоди (20+ хв)", "Длиннее эпизоды (20+ мин)", "Longer 20+ minute deep dives"),
                        "change": "Offer a 20-minute deep-dive length",
                        "test": "A listener picks 20 minutes and the next episode is 18–24 minutes long"},
    "text-transcript": {"title": _t("Текстова версія епізоду", "Текстовая версия эпизода", "A text transcript of each episode"),
                        "change": "Show a transcript with source links next to each episode in My podcasts",
                        "test": "Every ready episode in the library has a readable transcript with its source links"},
    "voice-choice": {"title": _t("Вибір голосів ведучих", "Выбор голосов ведущих", "Choosing the hosts' voices"),
                     "change": "Let the listener choose between at least three voice pairs",
                     "test": "A listener switches the voice pair and the next episode uses it"},
    "ask-follow-up": {"title": _t("Поставити питання після епізоду", "Задать вопрос после эпизода", "Asking a follow-up question"),
                      "change": "Add an 'ask about this episode' box that answers from the episode's sources",
                      "test": "A question about an episode gets an answer citing that episode's sources"},
    "offline-download": {"title": _t("Завантаження для офлайну", "Скачивание для офлайна", "Download for offline listening"),
                         "change": "Add a download button for ready episodes",
                         "test": "A ready episode downloads as an audio file that plays offline"},
    "shorter-setup": {"title": _t("Швидше налаштування", "Быстрее настройка", "A faster setup"),
                      "change": "Cut the configurator to a 3-step quick start with defaults",
                      "test": "A new listener gets to 'ready' in 3 steps or fewer"},
    "better-voices": {"title": _t("Природніші голоси", "Более естественные голоса", "More natural voices"),
                      "change": "Switch the default voices to the most natural available option and A/B them",
                      "test": "Listeners rate the new default voice higher than the old one in a blind pair"},
    "better-topic-match": {"title": _t("Точніші теми", "Более точные темы", "Topics that match better"),
                           "change": "Let the listener mark an item 'off topic' and use it to filter later episodes",
                           "test": "Items marked off topic stop appearing in the next three episodes"},
    "email-delivery": {"title": _t("Епізод на пошту", "Эпизод на почту", "Episodes by e-mail"),
                       "change": "Offer e-mail delivery of the daily episode next to Telegram",
                       "test": "A listener who chose e-mail receives the next episode by e-mail"},
    "podcast-app-feed": {"title": _t("Стрічка для подкаст-застосунку", "Лента для подкаст-приложения", "A private feed for podcast apps"),
                         "change": "Give each listener a private RSS feed for Apple Podcasts / Pocket Casts",
                         "test": "The private feed URL plays the latest episode in a podcast app"},
}


def _o(oid: str, uk: str, ru: str, en: str, theme: str = "", contra: tuple = ()) -> dict[str, Any]:
    return {"id": oid, "text": _t(uk, ru, en), "theme": theme, "contra": list(contra)}


QUIZZES: dict[str, dict[str, Any]] = {
    "mycast": {
        "version": "mycast-q1",
        "title": _t("Допоможіть покращити MyCast", "Помогите улучшить MyCast", "Help us improve MyCast"),
        "questions": [
            {"id": "q_use", "kind": "single", "text": _t("Як часто ви слухаєте MyCast?", "Как часто вы слушаете MyCast?", "How often do you listen to MyCast?"),
             "options": [_o("daily", "Щодня", "Каждый день", "Every day"), _o("weekly", "Кілька разів на тиждень", "Несколько раз в неделю", "A few times a week"),
                         _o("rarely", "Рідко", "Редко", "Rarely"), _o("not_yet", "Ще не слухав(ла)", "Ещё не слушал(а)", "Not yet")]},
            {"id": "q_length", "kind": "single", "text": _t("Яка довжина епізоду вам зручніша?", "Какая длина эпизода вам удобнее?", "Which episode length suits you?"),
             "options": [_o("short", "Коротко, 5 хв", "Коротко, 5 мин", "Short, 5 min", "shorter-episodes"),
                         _o("same", "Як зараз", "Как сейчас", "As it is now", "", ("shorter-episodes", "longer-episodes")),
                         _o("long", "Довше, 20+ хв", "Длиннее, 20+ мин", "Longer, 20+ min", "longer-episodes")]},
            {"id": "q_add", "kind": "multi", "max": 2, "text": _t("Що додати? (до двох)", "Что добавить? (до двух)", "What should we add? (up to two)"),
             "options": [_o("transcript", "Текст епізоду", "Текст эпизода", "A transcript", "text-transcript"),
                         _o("voices", "Вибір голосів", "Выбор голосов", "Voice choice", "voice-choice"),
                         _o("ask", "Питання до епізоду", "Вопрос к эпизоду", "Ask about the episode", "ask-follow-up"),
                         _o("offline", "Завантаження офлайн", "Скачивание офлайн", "Offline download", "offline-download"),
                         _o("nothing", "Нічого не треба", "Ничего не нужно", "Nothing")]},
            {"id": "q_fix", "kind": "single", "text": _t("Що заважає найбільше?", "Что мешает больше всего?", "What gets in the way most?"),
             "options": [_o("setup", "Довге налаштування", "Долгая настройка", "Setup takes too long", "shorter-setup"),
                         _o("voice", "Голос звучить штучно", "Голос звучит искусственно", "The voice sounds robotic", "better-voices"),
                         _o("topics", "Теми не ті", "Темы не те", "Topics miss the mark", "better-topic-match"),
                         _o("none", "Нічого не заважає", "Ничего не мешает", "Nothing")]},
            {"id": "q_channel", "kind": "single", "text": _t("Де вам зручніше отримувати епізод?", "Где вам удобнее получать эпизод?", "Where would you rather get your episode?"),
             "options": [_o("telegram", "Telegram, як зараз", "Telegram, как сейчас", "Telegram, as now", "", ("email-delivery", "podcast-app-feed")),
                         _o("email", "На пошту", "На почту", "By e-mail", "email-delivery"),
                         _o("app", "У подкаст-застосунку", "В подкаст-приложении", "In a podcast app", "podcast-app-feed"),
                         _o("web", "На сайті", "На сайте", "On the website")]},
        ],
        "free_text": _t("Своїми словами: що б ви змінили?", "Своими словами: что бы вы изменили?", "In your own words: what would you change?"),
    },
}


class QuizError(ValueError):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code, self.status = code, status


def _flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip() == "1"


def thresholds() -> dict[str, Any]:
    def num(name, default, cast):
        try:
            return cast(os.environ.get(name, "") or default)
        except ValueError:
            return default
    return {"min_people": max(3, num("FACTORY_QUIZ_MIN_PEOPLE", 10, int)),
            "min_share": min(1.0, max(0.1, num("FACTORY_QUIZ_MIN_SHARE", 0.40, float))),
            "auto_handoff": _flag("FACTORY_QUIZ_AUTO_V2", "1")}


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


class QuizService:
    """Quiz state in one JSON file (submissions index, caps, rewards, outbox, analyst log); feedback goes to T-630."""

    def __init__(self, path: Path, evolution: EvolutionStore, *, clock: Callable[[], float] = time.time,
                 create_ticket: Optional[Callable[..., dict]] = None,
                 grant_days: Optional[Callable[[str, int, str], bool]] = None):
        self.path, self.evo, self.clock = Path(path), evolution, clock
        self.create_ticket, self.grant_days = create_ticket, grant_days
        self._lock = threading.Lock()

    # --- storage -------------------------------------------------------------------------------------------------
    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("submissions"), dict) and data.get("salt"):
                for k, v in (("daily", {}), ("rewards", []), ("outbox", []), ("analyst", [])):
                    data.setdefault(k, v)
                return data
        except FileNotFoundError:
            return {"salt": secrets.token_hex(16), "submissions": {}, "daily": {}, "rewards": [], "outbox": [], "analyst": []}
        except (OSError, ValueError):
            pass
        raise QuizError("quiz_store_unreadable", 503)

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for k, cap in (("rewards", 5000), ("outbox", 5000), ("analyst", 300)):
            del data[k][:-cap]
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    # --- public quiz ---------------------------------------------------------------------------------------------
    def quiz(self, pid: str) -> dict[str, Any]:
        if pid not in QUIZZES:
            raise QuizError("unknown_quiz", 404)
        q = QUIZZES[pid]
        out = {"project": pid, "version": q["version"], "title": q["title"], "questions": q["questions"],
               "free_text": q["free_text"], "rewards_enabled": _flag("FACTORY_QUIZ_REWARDS"),
               "reward_days": REWARD_DAYS if _flag("FACTORY_QUIZ_REWARDS") else 0, "validate": None}
        lead = self._leading_theme(pid)
        if lead:  # adaptive: ask the next people whether the emerging theme really matters to them
            title = THEMES[lead]["title"]
            out["validate"] = {"theme": lead, "text": _t(f"Інші слухачі просять: «{title['uk']}». Ви б цим користувалися?",
                                                         f"Другие слушатели просят: «{title['ru']}». Вы бы этим пользовались?",
                                                         f"Other listeners ask for: “{title['en']}”. Would you use it?")}
        return out

    def _leading_theme(self, pid: str) -> str:
        try:
            view = self.evo.view(pid)
        except EvolutionError:
            return ""
        open_themes = {p.get("theme") for p in view["proposals"] if p["state"] != "declined"
                       and p["from_version"] == view["current_version"]}
        for th in view["themes"].get(view["current_version"], []):
            if th["theme"] in THEMES and th["theme"] not in open_themes and th["unique_support"] >= 3:
                return th["theme"]
        return ""

    def submit(self, pid: str, body: dict[str, Any], *, client: str, listener: str = "") -> dict[str, Any]:
        if pid not in QUIZZES:
            raise QuizError("unknown_quiz", 404)
        quiz = QUIZZES[pid]
        if body.get("consent") is not True:
            raise QuizError("consent_required")
        if body.get("version") != quiz["version"]:
            raise QuizError("quiz_changed", 409)
        answers = body.get("answers") if isinstance(body.get("answers"), dict) else {}
        chosen: dict[str, list[str]] = {}
        for q in quiz["questions"]:
            raw = answers.get(q["id"])
            if raw in (None, "", []):
                continue
            ids = raw if isinstance(raw, list) else [raw]
            ids = [str(i) for i in ids]
            valid = {o["id"] for o in q["options"]}
            if any(i not in valid for i in ids) or len(set(ids)) != len(ids):
                raise QuizError("bad_answer")
            if q["kind"] == "single" and len(ids) != 1 or q["kind"] == "multi" and len(ids) > q.get("max", 2):
                raise QuizError("bad_answer")
            chosen[q["id"]] = ids
        if len(chosen) < MIN_ANSWERS:
            raise QuizError("too_few_answers")
        free = clean_text(body.get("free_text"), FREE_TEXT_MAX)
        validate = body.get("validate") if isinstance(body.get("validate"), dict) else None
        email, contact = str(body.get("email") or "").strip()[:254], body.get("contact_consent") is True
        if email and (not contact or not EMAIL_RE.match(email)):
            raise QuizError("bad_email" if contact else "contact_consent_required")
        themes, contra = [], []
        # Codex review #412: an anonymous identity rotates daily, so one person could count as many. Only signed-in
        # listeners (one stable identity per quiz version) and people who actually used MyCast shape themes.
        used = bool(listener) and chosen.get("q_use", [""])[0] != "not_yet"
        if used:
            for q in quiz["questions"]:
                for oid in chosen.get(q["id"], []):
                    opt = next(o for o in q["options"] if o["id"] == oid)
                    if opt["theme"]:
                        themes.append(opt["theme"])
                    contra.extend(opt["contra"])
            if validate and validate.get("theme") in THEMES and validate.get("answer") in ("yes", "no"):
                (themes if validate["answer"] == "yes" else contra).append(validate["theme"])
        themes = list(dict.fromkeys(themes))[:5]
        contra = [c for c in dict.fromkeys(contra) if c not in themes][:5]
        now = self.clock()
        day = _day(now)
        with self._lock:
            data = self._load()
            ckey = hashlib.sha256(f"{data['salt']}|{day}|{client}".encode()).hexdigest()[:20]
            who = f"listener:{listener}" if listener else f"anon:{ckey}"
            phash = hashlib.sha256(f"{data['salt']}|{pid}|{quiz['version']}|{who}".encode()).hexdigest()[:24]
            if phash in data["submissions"]:
                raise QuizError("already_answered", 409)
            counts = data["daily"].setdefault(day, {"total": 0, "clients": {}})
            if counts["total"] >= GLOBAL_DAILY or counts["clients"].get(ckey, 0) >= PER_CLIENT_DAILY:
                raise QuizError("daily_limit", 429)
            sid = "qz-" + secrets.token_hex(5)
            labels = {q["id"]: ", ".join(next(o for o in q["options"] if o["id"] == i)["text"]["en"] for i in ids)
                      for q in quiz["questions"] for ids in [chosen.get(q["id"], [])] if ids}
            try:
                fb = self.evo.add_feedback(pid, {
                    "consent": True, "consent_ref": f"{pid}-quiz:{quiz['version']}:{sid}", "participant": who,
                    "source": "in_product", "tried": "yes" if used else "no",
                    "job": f"MyCast quiz {quiz['version']}: listens {labels.get('q_use', '?')}; length {labels.get('q_length', '?')}",
                    "helped": f"add: {labels.get('q_add', '—')}; channel: {labels.get('q_channel', '—')}",
                    "failed": "; ".join(x for x in (f"in the way: {labels['q_fix']}" if labels.get("q_fix") else "", free) if x),
                    "themes": themes, "contra": contra, "idempotency_key": f"quiz:{phash}"}, actor_role="agent", actor="quiz")
            except EvolutionError as exc:
                raise QuizError(exc.code, exc.status)
            fid = fb["feedback"]["id"]
            data["submissions"][phash] = {"id": sid, "at": _iso(now), "project": pid, "version": quiz["version"],
                                          "feedback_id": fid, "listener": listener or None, "counted": used,
                                          "email": email if (email and contact) else None}
            counts["total"] += 1
            counts["clients"][ckey] = counts["clients"].get(ckey, 0) + 1
            data["daily"] = {d: v for d, v in data["daily"].items() if d >= day}
            reward = self._reward(data, sid, listener)
            if email and contact:
                data["outbox"].append({"id": f"mail:{sid}:thanks", "at": _iso(now), "submission": sid, "template": "thanks",
                                       "status": "held_flag_off" if not _flag("FACTORY_QUIZ_MAIL") else "held_no_provider"})
            self._save(data)
        actions = self.analyze(pid)
        return {"id": sid, "counted": used, "reason": "" if used else ("sign_in_to_count" if not listener else "not_used_yet"),
                "reward": reward, "analyst": actions,
                "stored": ["answers", "free_text"] + (["email"] if email else [])}

    def _reward(self, data: dict, sid: str, listener: str) -> dict[str, Any]:
        """A gift is for a signed-in listener only, once per quiz version (the submission is already unique)."""
        if not listener:
            return {"status": "none", "reason": "sign_in_for_gift"}
        entry = {"id": f"reward:{sid}", "listener": listener, "days": REWARD_DAYS, "status": "held_flag_off"}
        if _flag("FACTORY_QUIZ_REWARDS") and self.grant_days:
            entry["status"] = "granted" if self.grant_days(listener, REWARD_DAYS, entry["id"]) else "not_granted"
        data["rewards"].append(entry)
        return {"status": entry["status"], "days": REWARD_DAYS if entry["status"] == "granted" else 0}

    # --- analyst agent -------------------------------------------------------------------------------------------
    def analyze(self, pid: str) -> list[dict[str, Any]]:
        """Propose a V2 change for each theme past the threshold and, under the standing rule, hand it to Builder."""
        cfg = thresholds()
        try:
            view = self.evo.view(pid)
        except EvolutionError:
            return []
        version = view["current_version"]
        taken = {p.get("theme") for p in view["proposals"] if p["state"] != "declined" and p["from_version"] == version}
        actions = []
        if cfg["auto_handoff"] and self.create_ticket:  # retry a hand-off that failed earlier (e.g. Relay down)
            for p in view["proposals"]:
                if p["state"] == "proposed" and p.get("proposed_by") == "agent" and p.get("theme") in THEMES \
                        and p["from_version"] == version and not p.get("synthetic"):
                    try:
                        done = self.evo.policy_handoff(pid, p["id"], policy=POLICY, evidence={"retry": True, "theme": p["theme"]},
                                                       create_ticket=self.create_ticket)["proposal"]
                        actions.append({"theme": p["theme"], "proposal": p["id"], "handoff": "handed_off", "ticket": done["ticket_id"], "retry": True})
                    except EvolutionError as exc:
                        actions.append({"theme": p["theme"], "proposal": p["id"], "error": exc.code, "retry": True})
        for th in view["themes"].get(version, []):
            name = th["theme"]
            if name not in THEMES or name in taken:
                continue
            if th["unique_support"] < cfg["min_people"] or th["share"] < cfg["min_share"] or th["unique_contra"] * 2 >= th["unique_support"]:
                continue
            spec = THEMES[name]
            evidence = {"theme": name, "people": th["unique_support"], "contrary": th["unique_contra"],
                        "sample": th["sample_size"], "share": th["share"], "min_people": cfg["min_people"],
                        "min_share": cfg["min_share"]}
            try:
                prop = self.evo.propose(pid, {
                    "title": spec["title"]["en"], "theme": name, "feedback_ids": th["support_ids"][:50],
                    "problem": f"{th['unique_support']} of {th['sample_size']} people ({round(th['share'] * 100)}%) asked for: "
                               f"{spec['title']['en']}; {th['unique_contra']} answered against.",
                    "change": spec["change"], "acceptance_test": spec["test"],
                    "idempotency_key": f"analyst:{pid}:{version}:{name}"}, actor_role="agent", actor="quiz-analyst")["proposal"]
                action = {"theme": name, "proposal": prop["id"], "handoff": "waiting_owner", **evidence}
                if cfg["auto_handoff"] and self.create_ticket:
                    done = self.evo.policy_handoff(pid, prop["id"], policy=POLICY, evidence=evidence,
                                                   create_ticket=self.create_ticket)["proposal"]
                    action["handoff"], action["ticket"] = "handed_off", done["ticket_id"]
            except EvolutionError as exc:
                action = {"theme": name, "error": exc.code}
            actions.append(action)
            with self._lock:
                data = self._load()
                data["analyst"].append(dict(action, at=_iso(self.clock()), project=pid, version=version))
                self._save(data)
        return actions

    # --- owner view / privacy ------------------------------------------------------------------------------------
    def stats(self, pid: str) -> dict[str, Any]:
        with self._lock:
            data = self._load()
        subs = [s for s in data["submissions"].values() if s["project"] == pid]
        return {"project": pid, "version": QUIZZES.get(pid, {}).get("version"), "thresholds": thresholds(),
                "submissions": len(subs), "counted": sum(1 for s in subs if s["counted"]),
                "signed_in": sum(1 for s in subs if s["listener"]), "with_email": sum(1 for s in subs if s["email"]),
                "rewards": {k: sum(1 for r in data["rewards"] if r["status"] == k) for k in ("held_flag_off", "granted", "not_granted")},
                "outbox": {k: sum(1 for m in data["outbox"] if m["status"] == k) for k in ("held_flag_off", "held_no_provider", "sent")},
                "flags": {"rewards": _flag("FACTORY_QUIZ_REWARDS"), "mail": _flag("FACTORY_QUIZ_MAIL")},
                "analyst": [a for a in data["analyst"] if a.get("project") == pid][-20:],
                "latest": [{k: s[k] for k in ("id", "at", "version", "feedback_id", "counted")} for s in subs[-30:]]}

    def delete(self, pid: str, sid: str) -> dict[str, Any]:
        with self._lock:
            data = self._load()
            key = next((k for k, s in data["submissions"].items() if s["id"] == sid and s["project"] == pid), None)
            if not key:
                raise QuizError("not_found", 404)
            fid = data["submissions"].pop(key)["feedback_id"]
            data["outbox"] = [m for m in data["outbox"] if m.get("submission") != sid]
            self._save(data)
        try:
            self.evo.delete_feedback(pid, fid, actor_role="owner", actor="quiz-privacy-delete")
        except EvolutionError:
            pass
        return {"deleted": sid}


def install_mvp_quiz_routes(app, service: QuizService, identity_fn: Callable, *,
                            listener_fn: Callable[[Request], str] = lambda request: "",
                            client_fn: Callable[[Request], str] = lambda request: "?") -> None:
    """Public: GET/POST /api/mycast/quiz (no sign-in; capped). Owner/member: stats. Owner: privacy delete."""

    def _err(exc: QuizError):
        return JSONResponse({"detail": exc.code}, status_code=exc.status)

    def _role(request: Request) -> str:
        return str((identity_fn(request) or {}).get("role") or "")

    @app.get("/api/mycast/quiz")
    def mycast_quiz():
        try:
            return service.quiz("mycast")
        except QuizError as exc:
            return _err(exc)

    @app.post("/api/mycast/quiz")
    async def mycast_quiz_submit(request: Request):
        try:
            body = await request.json()
        except (ValueError, TypeError):
            body = None
        if not isinstance(body, dict):
            return JSONResponse({"detail": "bad_body"}, status_code=400)
        try:
            return service.submit("mycast", body, client=client_fn(request), listener=listener_fn(request) or "")
        except QuizError as exc:
            return _err(exc)

    @app.get("/api/mvp-quiz/{project_id}/stats")
    def mvp_quiz_stats(project_id: str, request: Request):
        role = _role(request)
        if role not in ("owner", "member"):
            return JSONResponse({"detail": "login_required" if not role else "forbidden"}, status_code=401 if not role else 403)
        return service.stats(project_id)

    @app.post("/api/mvp-quiz/{project_id}/submissions/{submission_id}/delete")
    def mvp_quiz_delete(project_id: str, submission_id: str, request: Request):
        if _role(request) != "owner":
            return JSONResponse({"detail": "owner_only"}, status_code=403)
        try:
            return service.delete(project_id, submission_id)
        except QuizError as exc:
            return _err(exc)
