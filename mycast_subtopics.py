"""MyCast: AI subtopic suggestions for the configurator (owner 2026-11-11: "через нейронку, но по подписке, не по копеечке").

GET /api/mycast/subtopics?q=<topic>&lang=uk|ru|en → {"topics": [...], "source": "gemini"|"cache"|"limit"|"unavailable"}

- Gemini on the owner's free key (stable Flash, picked per key): no per-request bill. Bounded by DAILY_CAP new
  generations per UTC day and PER_CLIENT_CAP per visitor (hashed address, never stored raw); identical queries are
  served from a 30-day cache for free.
- Public (the configurator is a public beta page), so input and output are both cleaned: the query is limited to
  60 characters, suggestions to 6 items of at most 40 characters without markup.
- Anything that goes wrong returns 200 with an empty list; the page keeps its local templates. Never an error page.
- Data note: on the free Gemini tier Google may use prompts to improve its products; only the topic text is sent.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Callable, Optional

DAILY_CAP = 300
PER_CLIENT_CAP = 30
CACHE_DAYS = 30
MAX_QUERY = 60
LANGS = {"uk": "українською", "ru": "на русском", "en": "in English"}
_CLEAN = re.compile(r"[\u0000-\u001f<>{}\[\]`\\\\]")


def normalize(q: str) -> str:
    return " ".join(_CLEAN.sub(" ", str(q or "")).split())[:MAX_QUERY].strip()


def build_prompt(query: str, lang: str) -> str:
    return (f"A listener builds a personal daily news podcast and typed the interest: \"{query}\".\n"
            f"Suggest 6 narrower subtopics worth following daily, {LANGS.get(lang, 'in English')}, "
            "2-4 words each, no numbering, no emoji, no brand promotion, nothing unsafe.\n"
            'Answer with JSON only: {"topics": ["...", "..."]}')


def parse_topics(text: str, query: str) -> list:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").split("\n", 1)[-1]
    try:
        data = json.loads(raw)
    except ValueError:
        m = re.search(r"\{.*\}", raw, re.S)
        try:
            data = json.loads(m.group(0)) if m else {}
        except ValueError:
            data = {}
    items = data.get("topics") if isinstance(data, dict) else None
    out, seen = [], {query.lower()}
    for t in items or []:
        t = " ".join(_CLEAN.sub(" ", re.sub(r"<[^>]*>", "", str(t))).split()).strip(" .,-—")[:40]
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
        if len(out) >= 6:
            break
    return out


class SubtopicService:
    def __init__(self, root: Path, *, api_key: Callable[[], str], generate: Callable[[str, str], Optional[str]],
                 clock: Callable[[], float] = time.time, daily_cap: int = DAILY_CAP, per_client_cap: int = PER_CLIENT_CAP):
        """``generate(api_key, prompt) -> text | None`` (None on any provider error)."""
        self.root, self.api_key, self.generate, self.clock = Path(root), api_key, generate, clock
        self.daily_cap, self.per_client_cap = daily_cap, per_client_cap
        self._lock = threading.Lock()

    def _path(self) -> Path:
        return self.root / "subtopics.json"

    def _load(self) -> dict:
        try:
            data = json.loads(self._path().read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self._path().with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._path())

    def suggest(self, query: str, lang: str, client: str) -> dict:
        q, lang = normalize(query), lang if lang in LANGS else "en"
        if len(q) < 2:
            return {"topics": [], "source": "empty"}
        key = hashlib.sha256(f"{lang}:{q.lower()}".encode()).hexdigest()[:24]
        now = self.clock()
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        who = hashlib.sha256(str(client or "?").encode()).hexdigest()[:16]
        with self._lock:
            data = self._load()
            cache = {k: v for k, v in (data.get("cache") or {}).items() if now - float(v.get("at") or 0) < CACHE_DAYS * 86400}
            if key in cache:
                return {"topics": cache[key]["topics"], "source": "cache"}
            counts = data.get("counts") if (data.get("counts") or {}).get("day") == day else {"day": day, "total": 0, "clients": {}}
            if not self.api_key():
                return {"topics": [], "source": "unavailable"}
            if counts["total"] >= self.daily_cap or int(counts["clients"].get(who, 0)) >= self.per_client_cap:
                return {"topics": [], "source": "limit"}
            counts["total"] += 1
            counts["clients"][who] = int(counts["clients"].get(who, 0)) + 1
            data.update(counts=counts, cache=cache)
            self._save(data)
        try:
            text = self.generate(self.api_key(), build_prompt(q, lang))
        except Exception:
            text = None
        topics = parse_topics(text, q) if text else []
        if not topics:
            return {"topics": [], "source": "unavailable"}
        with self._lock:
            data = self._load()
            data.setdefault("cache", {})[key] = {"topics": topics, "at": now}
            if len(data["cache"]) > 5000:                        # bounded file
                for k in sorted(data["cache"], key=lambda k: data["cache"][k].get("at", 0))[:1000]:
                    data["cache"].pop(k, None)
            self._save(data)
        return {"topics": topics, "source": "gemini"}
