# FactoryOS: motion explainer storyboard (#353)

This is a concept film: **75 seconds, 9 shots, 16:9**, with a portrait reflow for phones. Everything shown is **DEMO** or **NO DATA**.

The film is a product vision plus an honest overview of the architecture. It is **not** evidence that every pipeline already runs end to end.

## Visual device

- **One luminous packet.** A single glowing packet stands for the task. It travels through the whole factory, and its label changes as it goes:
  `вопрос → доказательства → ТЗ → PR → задача → страницы → промо-черновики → наблюдения → решение`
- **The fork.** At the A/B split the packet becomes **two independent packets**:
  - A, cyan, always **on top**;
  - B, violet, always **below**.
  They merge again only at the evidence comparison.
- **The camera is an actor.**
  - It pushes through a physical monitor.
  - It flies from one department to the next, zooming in log space so the movement feels like a camera, not a slide.
  - It drifts slightly within each shot.
  - It ends on a large pull-back over the whole map.
- **One world map.** All departments sit on one map. The final pull-back shows the same objects the viewer has already seen, not a new diagram.

## Shot list

The camera keyframes are listed as `(cx, cy, view width)` in world units, in `CAM` inside `index.html`.

| # | Time | Camera and transition | What moves on screen | Kinetic caption (RU) |
|---|---|---|---|---|
| 1 | 0–5 s | Starts static on a desk monitor. At 2.6 s it **pushes through the screen**: CSS scale ×8, origin on the glowing dot. The world fades in under it at 3.4–4.8 s. | From frame 0, a tagline says what FactoryOS is. The idea appears on the console as a glowing dot, then becomes the packet `вопрос` on the "Идея" card. | Идея — начало. Дальше нужна система. |
| 2 | 5–13 s | Flies right to the debate cluster, then slowly pulls in. | Researcher, Critic and Strategist appear. Evidence nodes link up in sequence. The Critic challenges two of them. H1/H2/H3 appear; H2 and H3 are struck through as «отсеяна». The packet visits the evidence and leaves with H1. | Проверяем проблему и альтернативы. |
| 3 | 13–21 s | Flies to Product. | MVP Manager appears. The packet passes the research notes, the spec (label becomes `ТЗ`) and the acceptance criteria; three checks tick. An arrow reads «передаёт в сборку →». | Из гипотезы — в проверяемое ТЗ. |
| 4 | 21–31 s | Flies to Build. | The product preview assembles block by block. The chain ветка → PR → CI → ревью draws in. CI and review get `✓ sample` chips. Note: **«PR ≠ задеплоенное приложение»**. | Код плюс доказательства, а не «сделано» на словах. |
| 5 | 31–39 s | Flies to Agent Office and Relay. | A five-column board: `queued / claimed / running / review / done`. The packet card moves column by column. At `claimed` a chip reads **«назначено ≠ выполняется»**. The Relay journal adds `DEMO-1..3` events: claim, PR opened, handoff. | Назначение ≠ выполнение. |
| 6 | 39–49 s | Widens to the fork. | An A/B node appears with the note «A/B Tester — предложенная роль, ещё не работает». It splits into **A on top / B below**. Each branch gets its own audience, then landing, then Content Factory drafts, each marked DEMO. Two packets travel separately. | Две гипотезы — два независимых пути. |
| 7 | 49–59 s | Widens further to show both branches and the Owner. | The **Owner** card is linked to two gates. Each gate's lock is amber «ждёт решения» and turns green «одобрено владельцем (DEMO)» at 53.4 s (A) and 53.8 s (B). Behind each gate sit separate Facebook and TikTok packs, each with its own creative, CTA and URL, all DEMO. | Свой контент и своя кампания для каждой аудитории. |
| 8 | 59–68 s | Flies to Learn. | Two **separate funnels**: визит → регистрация → полезное действие → возврат. They have hatched bars and a **NO DATA** chip, with no numbers. They converge into «Сравнение доказательств — не рандомизированный тест», then «Решение». The feedback loop draws back along the bottom. | Решаем по действиям людей, а не по кликам. |
| 9 | 68–75 s | **Large pull-back** over the whole map: view width 1,640 → 7,800. | Department titles 1–8 appear. The supporting band appears: GitHub, Notion, Relay, Agent Office. The Owner is linked back to the idea. The decision packet rides the feedback loop back to «Идея» as a new `вопрос`. The end mark takes over the caption band. | FactoryOS. От идеи — к проверяемому результату. |

## Narration (RU, about 120 words; one line per shot)

1. Идея — только начало. Как понять, что людям это действительно нужно?
2. FactoryOS собирает вокруг задачи AI-специалистов: исследователь ищет доказательства, критик спорит, слабые гипотезы отсеиваются.
3. Менеджер MVP превращает выводы в спецификацию с критериями приёмки.
4. Билдер пишет код в отдельной ветке и открывает PR. Тесты и ревью — доказательство, а не слова. PR — ещё не запущенный продукт.
5. Relay фиксирует каждую передачу работы, Agent Office показывает, кто чем занят. Назначить — ещё не значит выполнить.
6. А если у идеи две версии? MVP Builder раскрывает две ветки: два лендинга и два набора материалов от Content Factory.
7. У каждой аудитории — своё промо. Перед реальным запуском владелец утверждает публикации и расходы.
8. Аналитика возвращает наблюдения: визит, регистрация, первое полезное действие, возврат. Решение уходит в новый цикл.
9. FactoryOS — от идеи к проверяемому результату.

UK and EN versions of every caption, narration line and on-map label live in the `L` dictionary in `index.html`. They switch with the RU/UK/EN selector.

## Claim check

| Shown | Status in the repo | How the film marks it |
|---|---|---|
| Owner decides, approves publishing and spend | Rule in `CLAUDE.md` / `AGENTS.md`: there is a human approval gate before publishing | Owner card and two gates. Approval is labelled DEMO. |
| AI roles debate an idea | Concept: Content Brain and Strategy agents exist; the debate is a product vision | Role names only; no claim that it is automatic |
| MVP Manager / MVP Builder | `mvp_factory.py`, `docs/MVP_FACTORY_SPEC.md` | Named as is |
| Branch → PR → CI → review | GitHub flow used by this repo | `✓ sample` chips, «PR ≠ задеплоенное приложение» |
| Relay claims and events, Agent Office state | Relay exists; the live two-way link is **not verified** (Issue #94) | Journal entries are `DEMO-n`; «назначено ≠ выполняется» |
| A/B Tester | Spec only (PR #347, review #348) | «предложенная роль, ещё не работает» |
| Content Factory drafts per audience | Drafts only; external publication is owner-gated | DEMO tags on every pack |
| Facebook / TikTok campaigns | Not running | DEMO tags; locks before every pack |
| Funnel metrics | None | Hatched bars plus **NO DATA**, no numbers |
| Cross-audience comparison | Not a randomized test | «не рандомизированный тест» |

The film has no invented users, revenue, testimonials, logos or live connections. The Notion storyboard's automatic-publishing scenarios were deliberately **not** used.

## Revision 2026-11-14 (owner feedback)

- **Readability.** Cards are wider, so no label overflows its box. The packet now docks *beside* cards: its label goes above or below, never over card text or arrows. In the A/B and promo shots, packet A rides above its lane and packet B below.
- **Promo shot.** The camera visits branch A together with the Owner first, then branch B (49–54.6 s on A, 56–59 s on B). This keeps text large. B's approval and its packs come after A's.
- **More explanation on screen:**
  - **Idea.** «у вас есть идея — вы её пишете».
  - **Debate.** Heading «2–3 AI-агента спорят об идее → находят концепцию». Each role is labelled:
    - исследователь: ищет факты;
    - критик: ищет слабые места;
    - стратег: собирает концепцию.
    Dropped hypotheses get a red «отсеяна» chip.
  - **Product.** «MVP Manager — превращает концепцию в ТЗ» and «ТЗ: что строим, для кого и как проверим результат».
  - **Build.** The heading «MVP Builder собирает продукт по частям» sits over the product preview, which is split into HTML-страница / логика / код-API / данные. Three agents are shown:
    - агент-фронтенд: верстает HTML;
    - агент-бэкенд: пишет код и логику;
    - агент-QA: гоняет тесты.
  - **Agent Office.** «по стратегии: 2 гипотезы → 2 теста».
  - **Fork.** «оба теста идут параллельно».
- Narration for shots 2–6 was updated to match, in RU, UK and EN.
- The film is also listed in the dashboard's new **Обучение** section (`/learn`), under «Обучалки по системе».
