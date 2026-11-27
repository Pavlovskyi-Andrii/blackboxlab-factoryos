"""Licensed stills from Wikimedia Commons for a Film Studio render (T-744, owner 2026-11-27: «вместо Pexels»).

Pexels stopped issuing API keys and its pages answer a Cloudflare challenge to data-centre sessions, so the shot pack
uses Commons instead: every file's licence, author and page come from the Commons API (`extmetadata`), not from a
guess. Only licences without share-alike or non-commercial terms are accepted (CC0, public domain, CC BY), so the film
itself can carry any licence later. Images are Wikimedia's standard 1920 px thumbnails (Commons refuses originals to
data-centre clients). The renderer stays offline: this module is the separate fetch step, like narration synthesis.

    python -m film_studio.commons --out /private/assets --pick s01="File:Minato City, Tokyo, Japan (Night).jpg" ...
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

API = "https://commons.wikimedia.org/w/api.php"
UA = "FactoryOS-FilmStudio/1.0 (private demo render; https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos)"
THUMB_WIDTH = 1920   # a standard Wikimedia thumbnail step; other widths answer HTTP 400 to API clients
ACCEPTED = re.compile(r"^(CC0( 1\.0)?|Public domain|PD-[\w-]+|CC BY [0-9.]+)$", re.I)
CC0_URL = "https://creativecommons.org/publicdomain/zero/1.0/"


def clean(html: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", str(html or ""))).strip()


def licence_record(title: str, imageinfo: Dict[str, Any]) -> Dict[str, Any]:
    """Licence facts from one Commons `imageinfo` entry; raises ValueError for a licence the film may not use."""
    md = imageinfo.get("extmetadata") or {}
    lic = clean((md.get("LicenseShortName") or {}).get("value"))
    if not ACCEPTED.match(lic):
        raise ValueError(f"{title}: licence {lic!r} is not CC0 / public domain / CC BY")
    url = clean((md.get("LicenseUrl") or {}).get("value")) or (CC0_URL if lic.upper().startswith("CC0") else "")
    if not url.startswith("https://"):
        url = "https://commons.wikimedia.org/wiki/Commons:Licensing"
    artist = clean((md.get("Artist") or {}).get("value"))[:200]
    if not artist:
        raise ValueError(f"{title}: no author in the Commons metadata")
    return {"licence": lic, "licence_url": url, "author": artist, "page": imageinfo["descriptionurl"],
            "attribution_required": clean((md.get("AttributionRequired") or {}).get("value")) == "true",
            "original_sha1": imageinfo.get("sha1", ""), "original_url": imageinfo["url"].split("?")[0]}


def thumb_url(original_url: str, width: int = THUMB_WIDTH) -> str:
    head, name = original_url.rsplit("/", 1)
    return head.replace("/wikipedia/commons/", "/wikipedia/commons/thumb/", 1) + f"/{name}/{width}px-{name}"


def manifest_asset(shot_id: str, substitutes_for: str, title: str, rec: Dict[str, Any], data: bytes,
                   verified_at: str) -> Dict[str, Any]:
    return {"id": f"commons-{shot_id}", "role": shot_id, "source_type": "licensed_stock", "provider": "Wikimedia Commons",
            "url": rec["page"], "author": rec["author"], "licence": {"name": rec["licence"], "url": rec["licence_url"]},
            "attribution": f"«{title[5:] if title.startswith('File:') else title}» by {rec['author']}, {rec['licence']} "
                           f"({rec['licence_url']}), via Wikimedia Commons"[:590],
            "changes": f"Wikimedia standard {THUMB_WIDTH} px thumbnail of the original (Commons sha1 "
                       f"{rec['original_sha1'][:12]}…); cropped/zoomed to 16:9 by the renderer",
            "rights_status": "verified", "verified_at": verified_at,
            "verified_by": "Commons API extmetadata (LicenseShortName, LicenseUrl, Artist, AttributionRequired)",
            "sha256": hashlib.sha256(data).hexdigest(), "local_path": f"commons-{shot_id}.jpg",
            "substitutes_for": substitutes_for}


def credits(assets: List[Dict[str, Any]]) -> str:
    """Plain-text photo credits for the film (CC BY requires them wherever the film is shown)."""
    lines = ["Фото / Photos:"]
    for a in assets:
        if a.get("source_type") == "licensed_stock":
            lines.append(f"{a['role']}: {a['attribution']} — {a['url']}")
    return "\n".join(lines) + "\n"


def _get(url: str, raw: bool = False, tries: int = 5):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Api-User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read() if raw else json.load(r)
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt == tries - 1:
                raise
            time.sleep(30 * (attempt + 1))   # Commons rate-limits data-centre clients; back off, never hammer


def fetch(out: Path, picks: List[tuple], get: Callable = _get, pause: float = 8.0) -> List[Dict[str, Any]]:
    """picks: [(shot_id, storyboard_asset_id, "File:…")]. Writes the JPEGs and commons_assets.json (resumable)."""
    out.mkdir(parents=True, exist_ok=True)
    store = out / "commons_assets.json"
    assets = json.loads(store.read_text(encoding="utf-8")) if store.is_file() else []
    done = {a["role"] for a in assets}
    for shot_id, sb_asset, title in picks:
        if shot_id in done:
            continue
        time.sleep(pause)
        q = {"action": "query", "format": "json", "titles": title, "prop": "imageinfo", "iiprop": "url|extmetadata|sha1"}
        page = next(iter(get(API + "?" + urllib.parse.urlencode(q))["query"]["pages"].values()))
        rec = licence_record(title, page["imageinfo"][0])
        time.sleep(pause)
        data = get(thumb_url(rec["original_url"]), raw=True)
        if data[:2] != b"\xff\xd8":
            raise ValueError(f"{title}: the thumbnail is not a JPEG")
        (out / f"commons-{shot_id}.jpg").write_bytes(data)
        assets.append(manifest_asset(shot_id, sb_asset, title, rec, data,
                                     time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
        store.write_text(json.dumps(assets, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "credits.txt").write_text(credits(assets), encoding="utf-8")
    return assets


def main(argv: Optional[List[str]] = None) -> int:
    from .render import SHOTPACK, RenderError, guard_private_output

    p = argparse.ArgumentParser(prog="python -m film_studio.commons", description=__doc__.split("\n\n")[0])
    p.add_argument("--out", required=True, help="private assets directory (outside the repository)")
    p.add_argument("--pick", action="append", default=[], help='shot_id="File:…" (repeatable)')
    p.add_argument("--storyboard", default=str(SHOTPACK / "storyboard.json"))
    a = p.parse_args(argv)
    try:
        guard_private_output(Path(a.out))
    except RenderError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    shots = {s["shot_id"]: s["asset_id"] for s in json.loads(Path(a.storyboard).read_text(encoding="utf-8"))["shots"]}
    picks = []
    for item in a.pick:
        sid, _, title = item.partition("=")
        if sid not in shots or not title.startswith("File:"):
            print(f"ERROR: bad --pick {item!r}", file=sys.stderr)
            return 2
        picks.append((sid, shots[sid], title))
    for asset in fetch(Path(a.out), picks):
        print(asset["role"], asset["licence"]["name"], "|", asset["author"][:60], "|", asset["url"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
