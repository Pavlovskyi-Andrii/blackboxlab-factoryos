"""#259: bounded GitHub list pagination shared by the Relay intake and the Team-tasks (EC2) snapshot.

GitHub returns at most 100 items per page. Reading only the first page hid older open owner issues from intake. This
reads page after page until a short page, and never more than ``max_pages`` pages (each one is a free, but rate-limited,
API call).

Fail closed: if any page fails, the exception propagates, so the caller reports GitHub as unavailable. It never
returns a silently partial list. When the page limit is reached with a full last page, ``truncated`` is True and the
caller can say so.
"""
from __future__ import annotations

from typing import Callable

PER_PAGE = 100
MAX_PAGES = 5


def fetch_all(fetch: Callable[[str], object], path: str, *, per_page: int = PER_PAGE, max_pages: int = MAX_PAGES) -> tuple[list, bool]:
    if not 1 <= per_page <= 100 or max_pages < 1:
        raise ValueError("bad pagination bounds")
    sep = "&" if "?" in path else "?"
    items: list = []
    for page in range(1, max_pages + 1):
        batch = fetch(f"{path}{sep}per_page={per_page}&page={page}")
        if not isinstance(batch, list):
            raise ValueError("Unexpected GitHub response")
        items.extend(batch)
        if len(batch) < per_page:
            return items, False
    return items, True
