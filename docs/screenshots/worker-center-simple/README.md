# Worker Center, simple mode (2026-11-17)

Local server with a seeded Relay ticket (R-0001: claimed → running → done) whose 🔄 detail was "delivered" to Telegram,
so the T-592 comparison card shows a real server verdict. Playwright, Chromium.

- `mobile-375-uk.png`, `mobile-375-ru.png` — first screen at 375 px: «Потрібно від вас / Нужно от вас: N», T-592-H and its
  Telegram ↔ site card first, every open HUMAN task as one row with «Як зробити / Как сделать».
- `mobile-375-ru-compare.png` — the runbook opened plus the comparison card with «Совпадает / Не совпадает».
- `mobile-375-ru-now.png` — folded «Сделано» / «Необязательно», «Сейчас работают» (one row per executor), and
  «Технические детали» closed.
- `desktop-1440-ru.png` — the same page on desktop.

Measured: `#dcBody` scrollWidth equals clientWidth at 375 px (no horizontal scrolling), no page errors. Pressing
«Совпадает» moves T-592-H to «Сделано» and the counter drops by one.
