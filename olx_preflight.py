"""OLX publish preflight: category rules and duplicate readback before any `POST /adverts` (Relay R-0110).

The owner agreed to a test duplicate of an existing advert, but never an accidental one. So before an approved draft
can be published, FactoryOS reads OLX (read-only, owner's user token) and records a preflight on the draft:
- the category is a leaf, the image count fits its `photos_limit`, every attribute the category marks
  `validation.required` is filled, select values are among the category's `values`, and no unknown attribute is sent
  (`GET /categories/{id}`, `GET /categories/{id}/attributes`);
- the owner's own adverts (`GET /adverts`, paged) are compared with the draft: same category + same normalised title
  in a live status = duplicate; an advert already carrying this draft's `external_id` blocks the publish (reconcile).

`check(...)` is the publish fence (`olx_publisher.publish_approved`): the preflight must be for this exact advert
(SHA-256), this OLX account, at most PREFLIGHT_MAX_AGE old, with no problems; duplicates (or an incomplete readback)
need the owner's explicit acknowledgement of exactly those advert ids. Only advert ids, statuses and OLX URLs are
stored — never titles of other adverts, OLX bodies or tokens. Existing adverts are only read, never changed.

`python -m olx_preflight` prints which OLX settings are present (names only, never values).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from typing import Callable

from fastapi import HTTPException, Request

PREFLIGHT_MAX_AGE = 1800                         # a readback older than 30 min is redone before publishing
PAGE_LIMIT = 50
PAGES_MAX = 20                                   # ≤ 1000 own adverts, ≤ 22 GETs: far below OLX's 4500 / 5 min / IP
LIVE = {"new", "active", "limited", "unconfirmed", "unpaid", "moderated"}
PRESENCE = ("FACTORY_OAUTH_OLX_CLIENT_ID", "FACTORY_OAUTH_OLX_CLIENT_SECRET", "FACTORY_VAULT_KEY",
            "FACTORY_OLX_ENABLED", "FACTORY_PUBLIC_BASE_URL")


def presence(env=None) -> dict:
    """Names → "present" / "missing". Values are never read out, printed or returned."""
    env = os.environ if env is None else env
    return {name: "present" if str(env.get(name, "")).strip() else "missing" for name in PRESENCE}


def title_key(title) -> str:
    return " ".join(re.findall(r"\w+", str(title or "").casefold()))


def _get(http, path: str, access_token: str, lang: str):
    import olx_publisher as op
    status, headers, raw = op._call(http, "GET", path, access_token, lang)
    if status == 429:
        try:
            wait = max(1, min(int(str((headers or {}).get("retry-after") or "60")), 3600))
        except ValueError:
            wait = 60
        raise HTTPException(429, "olx_rate_limited", headers={"Retry-After": str(wait)})
    if status != 200:
        op._raise_for(status, raw, write=False)
    return op._data(raw)


def category_problems(http, access_token: str, advert: dict, lang: str = "uk") -> list:
    """Fixed codes (attribute codes come from the draft's validated CODE_RE values or OLX's own codes)."""
    import olx_publisher as op
    cat_id = int(advert["category_id"])
    category = _get(http, f"/categories/{cat_id}", access_token, lang)
    category = category if isinstance(category, dict) else {}
    problems = []
    if category.get("is_leaf") is False:
        problems.append("olx_category_not_leaf")
    limit = category.get("photos_limit")
    if isinstance(limit, int) and not isinstance(limit, bool) and len(advert.get("images") or []) > limit:
        problems.append(f"olx_photos_over_limit_{limit}")
    defs = _get(http, f"/categories/{cat_id}/attributes", access_token, lang)
    defs = [d for d in (defs if isinstance(defs, list) else []) if isinstance(d, dict)
            and op.CODE_RE.fullmatch(str(d.get("code") or ""))]
    given = {a["code"]: a["value"] for a in advert.get("attributes") or []}
    known = set()
    for item in defs:
        code = str(item["code"])
        known.add(code)
        if code in ("price", "salary"):          # sent as the advert's `price` / `salary` object, not an attribute
            continue
        validation = item.get("validation") if isinstance(item.get("validation"), dict) else {}
        if validation.get("required") is True and code not in given:
            problems.append("olx_attribute_missing:" + code)
        values = [str(v.get("code")) for v in item.get("values") or [] if isinstance(v, dict) and v.get("code")]
        if code in given and values and validation.get("allow_multiple_values") is not True \
                and given[code] not in values:
            problems.append("olx_attribute_value:" + code)
    problems += ["olx_attribute_unknown:" + c for c in given if c not in known]
    return problems[:30]


def own_adverts(http, access_token: str, lang: str = "uk") -> tuple:
    """The owner's adverts as (rows, complete). Rows are kept in memory only."""
    rows, complete = [], False
    for page in range(PAGES_MAX):
        items = _get(http, f"/adverts?offset={page * PAGE_LIMIT}&limit={PAGE_LIMIT}", access_token, lang)
        items = [a for a in (items if isinstance(items, list) else []) if isinstance(a, dict)]
        rows += items
        if len(items) < PAGE_LIMIT:
            complete = True
            break
    if any("title" not in a or "category_id" not in a for a in rows):
        complete = False                         # cannot compare what OLX did not return: owner must look
    return rows, complete


def duplicates(rows: list, advert: dict, draft_id: str) -> tuple:
    """(same draft already on OLX, live look-alike receipts)."""
    import olx_publisher as op
    own = [op._receipt(a) for a in rows if str(a.get("external_id") or "") == draft_id]
    key, cat = title_key(advert.get("title")), str(advert.get("category_id"))
    alike = [op._receipt(a) for a in rows if str(a.get("external_id") or "") != draft_id
             and str(a.get("category_id")) == cat and title_key(a.get("title")) == key
             and str(a.get("status") or "") in LIVE]
    return [r for r in own if r], [r for r in alike if r][:20]


def run(http, access_token: str, account_id: str, draft: dict, lang: str = "uk", now: float | None = None) -> dict:
    import olx_publisher as op
    advert = draft["advert"]
    problems = category_problems(http, access_token, advert, lang)
    rows, complete = own_adverts(http, access_token, lang)
    mine, alike = duplicates(rows, advert, draft["id"])
    if mine:
        problems.append("olx_draft_already_on_olx_reconcile")
    return {"hash": op.advert_hash(advert), "account": account_id, "checked_at": int(now or time.time()),
            "problems": problems, "complete": complete, "duplicates": alike, "ack": []}


def needs_ack(record: dict) -> list:
    """Advert ids the owner must acknowledge (an incomplete readback needs the marker "incomplete")."""
    ids = sorted(d["advert_id"] for d in record.get("duplicates") or [])
    return ids + ([] if record.get("complete") else ["incomplete"])


def check(draft: dict, account_id: str, now: float | None = None) -> None:
    """The publish fence. Raises HTTPException(409, fixed code)."""
    import olx_publisher as op
    record = draft.get("preflight") if isinstance(draft.get("preflight"), dict) else None
    if not record or record.get("hash") != op.advert_hash(draft["advert"]) or record.get("account") != account_id:
        raise HTTPException(409, "olx_preflight_required")
    if (now or time.time()) - int(record.get("checked_at") or 0) > PREFLIGHT_MAX_AGE:
        raise HTTPException(409, "olx_preflight_stale")
    if record.get("problems"):
        raise HTTPException(409, "olx_preflight_problems")
    if needs_ack(record) and sorted(record.get("ack") or []) != needs_ack(record):
        raise HTTPException(409, "olx_duplicate_needs_ack")


def install_routes(app, *, store, owner: Callable, read_tokens: Callable, transport: Callable, lang: Callable,
                   body: Callable) -> None:
    """Called from `olx_publisher.install_routes` (keeps app.py untouched)."""
    import olx_publisher as op

    @app.post("/api/factory/olx/drafts/{draft_id}/preflight")
    def olx_preflight(draft_id: str, request: Request):
        """Read-only OLX readback for an approved draft; the result is stored on the draft."""
        owner(request)
        draft = store.get(draft_id)
        store.check_publishable(draft_id)
        tokens = read_tokens()
        try:
            record = run(transport(), tokens.access_token, tokens.account_id, draft, lang())
        except op.OlxError as exc:
            raise HTTPException(502, exc.code) from None
        return {"draft": store.set_preflight(draft_id, record, expect_hash=record["hash"]),
                "needs_ack": needs_ack(record)}

    @app.post("/api/factory/olx/drafts/{draft_id}/preflight/ack")
    async def olx_preflight_ack(draft_id: str, request: Request):
        """The owner confirms this one publish despite the listed look-alikes (e.g. a deliberate test duplicate)."""
        owner(request)
        data = await body(request)
        if data.get("confirm") is not True:
            raise HTTPException(400, "confirm: true required")
        draft = store.get(draft_id)
        record = draft.get("preflight") if isinstance(draft.get("preflight"), dict) else None
        if not record or record.get("hash") != op.advert_hash(draft["advert"]):
            raise HTTPException(409, "olx_preflight_required")
        ids = sorted(str(x) for x in data.get("advert_ids") or []) if isinstance(data.get("advert_ids"), list) else []
        if not needs_ack(record) or ids != needs_ack(record):
            raise HTTPException(409, "olx_ack_must_list_exactly_the_found_adverts")
        return {"draft": store.set_preflight(draft_id, {**record, "ack": ids}, expect_hash=record["hash"])}

    @app.get("/api/factory/olx/adverts/{advert_id}")
    def olx_advert_readback(advert_id: str, request: Request):
        """Read-only status of any own OLX advert by id (e.g. an advert created outside FactoryOS)."""
        owner(request)
        if not re.fullmatch(r"\d{1,20}", advert_id or ""):
            raise HTTPException(400, "olx_advert_id")
        tokens = read_tokens()
        try:
            return {"advert": op.get_advert(transport(), tokens.access_token, advert_id, lang())}
        except op.OlxError as exc:
            raise HTTPException(404 if exc.code == "olx_not_found" else 502, exc.code) from None


if __name__ == "__main__":
    json.dump(presence(), sys.stdout, indent=1)
    sys.stdout.write("\n")
