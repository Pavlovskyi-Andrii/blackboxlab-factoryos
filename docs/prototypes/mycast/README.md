# MyCast — standalone interactive mockup

**Owner:** ChatGPT · **Depends:** none for the UX-only prototype · **Issue:** #105 · **PR:** #107
**Status:** work-in-progress mockup, not a deployed application.

## Open the prototype
1. Open [index.html](./index.html) in GitHub, click **Download raw file** (or save the HTML file).
2. Open the downloaded `index.html` in a modern browser on a computer or phone. No build command, login or local server is needed.
3. Start at the animated globe, then use **Створити моє радіо** to choose news categories and subcategories, add custom interests, up to 10 YouTube channels and optional books.
4. At the final step, click **▶ Показати роботу агентів**. Alternatively scroll to the newsroom and click **▶ Відтворити історію**.
5. Watch Scout → Researcher → Editor → Producer handoffs, or click individual workers / **Наступний агент**. See selected interests propagate into the story and the illustrative 08:00 phone delivery.
6. Save preferences locally or copy the generated prompt. You can reconfigure the interests and replay.

## How the demo maps to the proposed product
- World news globe and curved glowing lines: a visual metaphor, not actual flight/news data.
- Scouts 3,000 → 30; Researcher 30 → 12; Editor 12 → 10 minutes; Producer → 08:00 phone: **illustrative figures and presentation only**.
- Proposed eventual pipeline: source discovery → source verification → editorial shortening → synthetic two-host audio and authorized delivery.
- Future real implementation must preserve citations, original published times, privacy class, rights checks, and clear uncertainty for claims.
- A real 08:00 delivery requires a scheduler, an audio engine, opt-in notification channel, consent and tests.
- No real AI, news ingestion, YouTube scraping, book summaries, microphone, audio or Telegram send. No API keys or paid services.

## Verification
- HTML + inline JavaScript syntax and element IDs checked during authoring.
- No manual mobile/desktop cross-browser test completed yet.
- Respects prefers-reduced-motion. Keyboard accessible buttons; accessibility audit pending.
- No deployment, no merge to main and no new paid infrastructure.
