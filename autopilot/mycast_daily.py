"""T-603: one MyCast episode per morning for the owner, between worker tasks.

1. Claude (existing subscription, web search/fetch only) writes the episode script as JSON.
2. The script is committed to branch `mycast/daily` through the GitHub API (the worker checkout is untouched).
3. GitHub Actions renders it with Piper TTS (zero spend); the worker downloads the mp3.
4. The FactoryOS server sends it to the owner's paired Telegram chat (the bot token stays on the server).
"""
from __future__ import annotations

import base64
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    KYIV = ZoneInfo("Europe/Kyiv")
except Exception:  # tzdata missing: fixed winter offset, documented in DECISIONS.md
    KYIV = timezone(timedelta(hours=2))

try:
    from . import notify, relay_tasks
    from .delegation import LIMIT_API_ERRORS, cli_error_fields, delegated_env
except ImportError:
    import notify
    import relay_tasks
    from delegation import LIMIT_API_ERRORS, cli_error_fields, delegated_env

REPO_SLUG = "Pavlovskyi-Andrii/blackboxlab-factoryos"
BRANCH = "mycast/daily"
EPISODE_DIR = "docs/prototypes/mycast/episodes"
WORKFLOW = "mycast-render.yml"
# Owner target (#219): the episode is in Telegram by 06:00 Kyiv. Writing the script (web search) and the
# Gemini voices take ~15-25 min, so the first attempt starts at 05:10; nothing runs before that.
START_HOUR, START_MINUTE = 5, 10
MAX_ATTEMPTS = 3        # per day
RENDER_WAIT_SECONDS = 1200
HOSTS = {"A": {"name": "Клод", "speaker": "mykyta"}, "B": {"name": "Джі-Пі-Ті", "speaker": "tetiana"}}

PROMPT = """Ти пишеш сценарій щоденного персонального подкасту MyCast для власника FactoryOS на {date}.
Знайди веб-пошуком свіжі новини (опубліковані за останні 48 годин) і напиши живу розмову двох ведучих українською.

Структура (відгук власника: менше списку, більше розмови і висновків):
1. Світ AI і технологій — 3–4 найважливіші новини, не більше. Перевірені релізи OpenAI, Anthropic, Google та великі події індустрії.
   Для кожної: що сталося → чому це важливо → як це можна вбудувати або використати у FactoryOS (конкретна ідея, позначена як ідея, а не план).
2. Гроші і стартапи — 1–2 події з сумами та джерелом, і чого з них може навчитися Blackbox Lab.
3. Наша кухня FactoryOS — 4–6 реплік простими словами: що вчора зробили білдери (Claude, ChatGPT, Gemini) і що в планах на сьогодні.
   ТІЛЬКИ з блоку «Факти FactoryOS» нижче. Без номерів задач, PR та issue, без внутрішніх кодів — лише суть, як для людини.
4. Глибше — один практичний сценарій використання AI для власника, з готовим промптом, який можна одразу скопіювати (продиктуй повільно, дослівно).

Факти FactoryOS (з репозиторію, на {date}):
{factory_status}

Правила:
- Лише факти з джерел, які ти реально відкрив; кожне джерело — у sources з датою. Чутки позначай словами «за даними…» або «поки не підтверджено».
- Ведучі: A — «Клод», B — «Джі-Пі-Ті». Вони розмовляють, реагують, ставлять одне одному питання, іноді не погоджуються. Кожна новина закінчується висновком «що це означає для нас». Без вигаданих особистих історій.
- Назви компаній, продуктів, моделей і технічні терміни пиши ЛАТИНИЦЕЮ, як в оригіналі (OpenAI, Claude Code, Gemini 3.8 Flash, API, SDK) — озвучка Gemini вимовляє їх правильно. Не транслітеруй їх кирилицею. Номери версій моделей — цифрами; інші числа (суми, відсотки, дати) — словами.
- Обсяг: 750–1100 слів (5–8 хвилин). Якщо свіжих перевірених новин мало — краще коротше, ніж вигадувати. Без markdown, емодзі та посилань у репліках.
- Перша репліка: привітання, дата і одним реченням — три головні теми випуску. Остання: коротке прощання.

Відповідь — ЛИШЕ JSON без пояснень:
{{"title": "MyCast · {date_human}", "sources": [{{"title": "...", "url": "https://...", "date": "YYYY-MM-DD"}}], "lines": [["A", "..."], ["B", "..."]]}}
"""


def log(message: str) -> None:
    print(f"mycast: {message}", file=sys.stderr, flush=True)


def today_kyiv(now: float | None = None) -> datetime:
    return datetime.fromtimestamp(time.time() if now is None else now, KYIV)


def load_state(path: pathlib.Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        value = {}
    return value if isinstance(value, dict) else {}


def save_state(path: pathlib.Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


RETRY_SPACING_SECONDS = 1200


def due(state: dict, now: float | None = None) -> bool:
    current = time.time() if now is None else now
    local = today_kyiv(current)
    if (local.hour, local.minute) < (START_HOUR, START_MINUTE):
        return False
    day = local.date().isoformat()
    if state.get("delivered_date") == day:
        return False
    attempts = state.get("attempts", {}).get(day, 0) if isinstance(state.get("attempts"), dict) else 0
    if attempts >= MAX_ATTEMPTS:
        return False
    # Space retries out: at most one attempt per 30 minutes.
    return current - float(state.get("last_attempt_ts") or 0) >= RETRY_SPACING_SECONDS


def validate(episode: dict) -> list[str]:
    problems = []
    if not isinstance(episode, dict):
        return ["not an object"]
    lines = episode.get("lines")
    if not isinstance(lines, list) or not 6 <= len(lines) <= 80:
        problems.append("lines: need 6–80 entries")
    else:
        for n, line in enumerate(lines):
            if not (isinstance(line, list) and len(line) == 2 and line[0] in HOSTS and isinstance(line[1], str) and 0 < len(line[1]) <= 900):
                problems.append(f"line {n}: must be [A|B, text ≤900 chars]")
                break
        words = sum(len(str(t).split()) for _, t in lines if isinstance(t, str))
        if not 300 <= words <= 1300:
            problems.append(f"length {words} words (want 300–1300)")
    sources = episode.get("sources")
    if not isinstance(sources, list) or not sources:
        problems.append("sources: at least one required")
    else:
        for s in sources:
            if not (isinstance(s, dict) and str(s.get("url", "")).startswith("https://") and s.get("title")):
                problems.append("sources: each needs title and https url")
                break
    return problems


def _extract_json(text: str) -> dict | None:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        return None


LANES = (("claude/", "Claude"), ("ccr-", "Claude"), ("gemini/", "Gemini"), ("chatgpt/", "ChatGPT"), ("autopilot/", "Claude"))
_IDS = re.compile(r"\(?#\d+\)?|\bT-\d+[\w-]*|\bP[0-3]\b|^(Gemini|ChatGPT|Claude)\s*[:·]\s*|\s*·\s*(?=·|$)")


def _lane(branch: str) -> str:
    return next((name for prefix, name in LANES if branch.startswith(prefix)), "команда")


def _plain(title: str) -> str:
    """A PR/task title the hosts can say aloud: no issue/PR/task numbers or priority codes."""
    text = title
    for _ in range(3):
        text = _IDS.sub("", text).strip(" ·:—-")
    return re.sub(r"\s{2,}", " ", text)[:110]


def factory_status(repo: pathlib.Path | None, *, runner=subprocess.run) -> str:
    """Owner-facing FactoryOS facts: what each builder merged yesterday, what is open now, what is next. Fail-soft."""
    if repo is None:
        return "- немає даних із репозиторію сьогодні; про FactoryOS скажи лише це"
    facts: list[str] = []

    def run(cmd: list[str]) -> str:
        try:
            return runner(cmd, text=True, capture_output=True, timeout=30, check=False).stdout or ""
        except (OSError, subprocess.TimeoutExpired):
            return ""

    done = []
    for row in run(["git", "-C", str(repo), "log", "--merges", "--since=30 hours ago", "--format=%s\x1f%b\x1e", "-n", "12",
                    "origin/main"]).split("\x1e"):
        if "\x1f" not in row:
            continue
        subject, body = row.split("\x1f", 1)
        m = re.search(r"from [^/\s]+/(\S+)", subject)
        title = _plain((body.strip().splitlines() or [""])[0])
        if title:
            done.append(f"- вчора зробив(ла) {_lane(m.group(1) if m else '')}: {title}")
    facts += done[:8] or ["- за останню добу нових злиттів у main не було"]
    try:
        prs = json.loads(run(["gh", "pr", "list", "-R", REPO_SLUG, "--state", "open", "--limit", "20",
                              "--json", "title,headRefName,isDraft"]) or "[]")
    except ValueError:
        prs = []
    active = [p for p in prs if isinstance(p, dict) and not p.get("isDraft")][:4]
    facts += [f"- зараз на перевірці у {_lane(str(p.get('headRefName', '')))}: {_plain(str(p.get('title', '')))}" for p in active]
    try:
        roadmap = (repo / "ROADMAP.md").read_text(encoding="utf-8")
        nxt = [m.group(1) for m in re.finditer(r"^- \[ \] (?!\[HUMAN\])\S+ (.+)$", roadmap, re.M)][:3]
        facts += [f"- у плані на сьогодні: {_plain(t)}" for t in nxt]
    except OSError:
        pass
    return "\n".join(facts)


def generate_episode(day: datetime, *, run_cli=None, status_text: str = "") -> tuple[str, dict | None]:
    """Returns (status, episode). status: ok | limit | failed."""
    date_iso = day.date().isoformat()
    months = ["січня", "лютого", "березня", "квітня", "травня", "червня", "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"]
    date_human = f"{day.day} {months[day.month - 1]} {day.year}"
    cmd = ["claude", "-p", PROMPT.format(date=date_iso, date_human=date_human,
                                          factory_status=status_text or factory_status(None)), "--output-format", "json",
           "--max-turns", "25", "--allowedTools", "WebSearch", "WebFetch",
           "--disallowedTools", "Bash", "Edit", "Write", "NotebookEdit", "Task"]
    try:
        result = (run_cli or subprocess.run)(cmd, cwd=tempfile.gettempdir(), env=delegated_env(), text=True,
                                             capture_output=True, timeout=900, check=False)
        out = str(result.stdout or "") + str(result.stderr or "")
    except (subprocess.TimeoutExpired, OSError) as exc:
        log(f"script generation did not run: {type(exc).__name__}")
        return "failed", None
    fields = cli_error_fields(out)
    if fields.get("api_error") in LIMIT_API_ERRORS or fields.get("api_error_status") == 429:
        return "limit", None
    try:
        wrapper = json.loads(str(result.stdout).strip().splitlines()[-1])
        text = str(wrapper.get("result") or "") if isinstance(wrapper, dict) and not wrapper.get("is_error") else ""
    except (ValueError, IndexError):
        text = ""
    episode = _extract_json(text)
    if episode is None:
        log("script generation returned no JSON")
        return "failed", None
    episode.update(id=f"mycast-{date_iso}", language="uk", voice_model="uk_UA-ukrainian_tts-medium", hosts=HOSTS,
                   note="Generated by Claude from web sources for the owner only; facts are attributed, not independently confirmed. Hosts are synthetic voices.")
    problems = validate(episode)
    if problems:
        log("script rejected: " + "; ".join(problems))
        return "failed", None
    return "ok", episode


def gh(*args: str, input_text: str | None = None, runner=subprocess.run) -> tuple[int, str]:
    result = runner(["gh", *args], text=True, capture_output=True, input=input_text, timeout=120, check=False)
    return result.returncode, (result.stdout or "").strip()


def publish(episode: dict, *, gh_fn=gh) -> str:
    """Commit the episode JSON to BRANCH via the GitHub API. Returns the new commit sha ('' on failure)."""
    code, main_sha = gh_fn("api", f"repos/{REPO_SLUG}/git/ref/heads/main", "--jq", ".object.sha")
    if code or not main_sha:
        return ""
    code, _ = gh_fn("api", f"repos/{REPO_SLUG}/git/ref/heads/{BRANCH}")
    if code:  # create the branch from main the first time
        code, _ = gh_fn("api", "-X", "POST", f"repos/{REPO_SLUG}/git/refs", "-f", f"ref=refs/heads/{BRANCH}", "-f", f"sha={main_sha}")
        if code:
            return ""
    path = f"{EPISODE_DIR}/{episode['id'][len('mycast-'):]}.json"
    code, existing = gh_fn("api", f"repos/{REPO_SLUG}/contents/{path}?ref={BRANCH}", "--jq", ".sha")
    body = {"message": f"MyCast daily episode {episode['id']}", "branch": BRANCH,
            "content": base64.b64encode(json.dumps(episode, ensure_ascii=False, indent=1).encode("utf-8")).decode("ascii")}
    if code == 0 and existing:
        body["sha"] = existing
    code, sha = gh_fn("api", "-X", "PUT", f"repos/{REPO_SLUG}/contents/{path}", "--input", "-", "--jq", ".commit.sha",
                      input_text=json.dumps(body))
    return sha if code == 0 else ""


def wait_render(commit_sha: str, *, gh_fn=gh, sleep=time.sleep, wait_seconds: int = RENDER_WAIT_SECONDS) -> str:
    """Returns the successful run id for the commit, or ''."""
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        code, out = gh_fn("run", "list", "-R", REPO_SLUG, "--workflow", WORKFLOW, "--commit", commit_sha,
                          "--json", "databaseId,status,conclusion", "--limit", "1")
        runs = json.loads(out) if code == 0 and out.startswith("[") else []
        if runs and runs[0].get("status") == "completed":
            return str(runs[0]["databaseId"]) if runs[0].get("conclusion") == "success" else ""
        sleep(20)
    return ""


def download_mp3(run_id: str, episode_id: str, *, gh_fn=gh) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        code, _ = gh_fn("run", "download", run_id, "-R", REPO_SLUG, "-n", "mycast-episodes", "-D", tmp)
        mp3 = pathlib.Path(tmp) / f"{episode_id}.mp3"
        return mp3.read_bytes() if code == 0 and mp3.exists() else b""


def deliver_gemini(episode: dict) -> str:
    """Server-side Gemini voices. Returns sent | duplicate | unavailable (→ Piper fallback)."""
    import requests

    url, token = relay_tasks.endpoint()
    if not url or not token:
        return "unavailable"
    try:
        response = requests.post(url + "/api/factory/mycast/worker/voice-deliver", headers={"Authorization": "Bearer " + token},
                                 json={"episode": episode}, timeout=1200)
    except requests.RequestException as exc:
        log(f"gemini voice request failed: {type(exc).__name__}; falling back to Piper")
        return "unavailable"
    if response.status_code == 200:
        body = response.json()
        log(f"delivered to Telegram with Gemini voices ({body.get('seconds', '?')} s, {body.get('bytes', '?')} bytes)"
            if body.get("sent") else "already delivered earlier")
        return "sent" if body.get("sent") else "duplicate"
    try:
        reason = str(response.json().get("detail", ""))[:60]
    except ValueError:
        reason = ""
    log(f"gemini voice unavailable (HTTP {response.status_code} {reason}); falling back to Piper")
    return "unavailable"


def deliver(episode: dict, audio: bytes) -> bool:
    import requests

    url, token = relay_tasks.endpoint()
    if not url or not token:
        return False
    words = sum(len(t.split()) for _, t in episode["lines"])
    links = "\n".join(f"• {s['title'][:80]}" for s in episode.get("sources", [])[:6])
    response = requests.post(url + "/api/factory/mycast/worker/deliver", headers={"Authorization": "Bearer " + token},
                             data={"episode_id": episode["id"], "title": episode.get("title", episode["id"]),
                                   "caption": f"🎧 {episode.get('title', '')} · ~{max(1, round(words / 140))} хв\n{links}"},
                             files={"audio": (episode["id"] + ".mp3", audio, "audio/mpeg")}, timeout=180)
    if response.status_code != 200:
        log(f"delivery failed: HTTP {response.status_code}")
        return False
    log("delivered to Telegram" if response.json().get("sent") else "already delivered earlier")
    return True


TELEGRAM_TEXT_LIMIT = 3900


def transcript_messages(episode: dict) -> list[str]:
    """Sources (with links) and the full written transcript, split into Telegram-sized messages."""
    hosts = {k: v["name"] for k, v in HOSTS.items()}
    head = f"📝 {episode.get('title', episode.get('id', 'MyCast'))} — текст і джерела"
    sources = "\n".join(f"• {s.get('title', '')[:100]} ({s.get('date', 'без дати')})\n  {s.get('url', '')}"
                        for s in episode.get("sources", [])[:12])
    parts, current = [], head + "\n\nДжерела:\n" + sources + "\n\nТекст:"
    for host, text in episode.get("lines", []):
        line = f"{hosts.get(host, host)}: {text}"
        if len(current) + len(line) + 2 > TELEGRAM_TEXT_LIMIT:
            parts.append(current)
            current = ""
        current = (current + "\n\n" + line).strip()
    if current:
        parts.append(current)
    return parts


def notify_owner(text: str, *, send=None) -> bool:
    """Owner-only Telegram message through the paired worker bot. Never raises."""
    try:
        return bool((send or notify.send)(text))
    except Exception as exc:  # a notice must never break the worker loop
        log(f"owner notice failed: {type(exc).__name__}")
        return False


def _send_transcript(episode: dict, state: dict, day: str, *, send=None) -> None:
    if state.get("transcript_date") == day:
        return
    if all(notify_owner(part, send=send) for part in transcript_messages(episode)):
        state["transcript_date"] = day


def run_daily(state_path: pathlib.Path, *, now: float | None = None, run_cli=None, repo: pathlib.Path | None = None,
              send=None) -> str:
    """One attempt if due. Returns: idle | delivered | limit | failed.

    Audio goes out once per day (server-side idempotency per episode id as well). The written transcript with
    sources follows the audio. If audio fails, the owner gets the transcript as a text fallback and, after the
    last attempt, an explicit failure notice — never a claim that audio was delivered."""
    if not relay_tasks.configured():  # no FactoryOS connection: nowhere to deliver
        return "idle"
    state = load_state(state_path)
    if not due(state, now):
        return "idle"
    local = today_kyiv(now)
    day = local.date().isoformat()
    attempts = state.setdefault("attempts", {})
    attempts[day] = attempts.get(day, 0) + 1
    state["attempts"] = {k: v for k, v in attempts.items() if k >= (local.date() - timedelta(days=7)).isoformat()}
    state["last_attempt_ts"] = time.time() if now is None else now
    save_state(state_path, state)
    last_attempt = state["attempts"][day] >= MAX_ATTEMPTS
    log(f"attempt {attempts[day]}/{MAX_ATTEMPTS} for {day}")

    def failed(reason: str, episode: dict | None = None) -> str:
        if episode is not None:
            _send_transcript(episode, state, day, send=send)  # text fallback: the owner can read it now
        if last_attempt and state.get("failure_notice_date") != day:
            fallback = " Текст випуску надіслано вище." if state.get("transcript_date") == day else ""
            if notify_owner(f"⚠️ MyCast {day}: аудіо сьогодні не доставлено ({reason}), "
                            f"спроб {MAX_ATTEMPTS}/{MAX_ATTEMPTS}.{fallback} Автоматично більше не повторюю.", send=send):
                state["failure_notice_date"] = day
        save_state(state_path, state)
        return "failed"

    status, episode = generate_episode(local, run_cli=run_cli, status_text=factory_status(repo))
    if status != "ok":
        if status == "limit":
            state["attempts"][day] -= 1  # a subscription limit is not the episode's fault
            save_state(state_path, state)
            return status
        return failed("сценарій не згенеровано")
    sha = publish(episode)  # the script is kept on mycast/daily either way (history, Piper fallback)
    voice = deliver_gemini(episode)
    if voice in ("sent", "duplicate"):
        state["delivered_date"] = day
        _send_transcript(episode, state, day, send=send)
        save_state(state_path, state)
        return "delivered"
    if not sha:
        log("publishing the script to GitHub failed")
        return failed("голоси Gemini недоступні, а резервний Piper не запустився", episode)
    log(f"script committed {sha[:10]}; waiting for render")
    run_id = wait_render(sha)
    audio = download_mp3(run_id, episode["id"]) if run_id else b""
    if not audio:
        log("render or download failed")
        return failed("голоси Gemini недоступні, резервний Piper не відрендерився", episode)
    if not deliver(episode, audio):
        return failed("Telegram не прийняв аудіо", episode)
    state["delivered_date"] = day
    _send_transcript(episode, state, day, send=send)
    save_state(state_path, state)
    return "delivered"
