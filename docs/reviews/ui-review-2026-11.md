# FactoryOS UI review — 2026-11-01 (T-595 / Issue #88)

**Источник:** GitHub Actions `FactoryOS CI` run [#41304341016](https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/actions/runs/41304341016) on `main`, **success**, artifact `ui-screenshots` id `13083380060`. Получены и визуально просмотрены PNG из ZIP; 3 языка × 3 размера × 6 сцен = **54 изображения**. Дата осмотра: **2026-11-01**. Это фиксированные CI-снимки, **не** проверка production UI. `get_design_context` / `submit_design_review` инструментов в доступном наборе нет; результат представлен PR.

Автоматический отчёт `summary.md`: **no horizontal overflow / page errors / failed actions**. Это не исключает clipping внутри отдельных flex-контейнеров и не измеряет визуальную доступность.

## Вывод по трём заранее известным проблемам

1. **Правая часть верхней панели, 390 px:** **подтверждено**. На `en/mobile-390x844/home.png` и `ru/mobile-390x844/home.png` видна кнопка `Share Viewer` с обрезанным правым контуром / подписью, в RU виден `Share Vie...`. При этом документ не даёт глобального горизонтального scroll — значит, клиппинг локальный.
2. **Agent Office + Offline chips, desktop:** **подтверждено как нарушение компоновки, но не полное перекрытие заголовка**. На `en/desktop-1440x900/home.png` чипы Claude/ChatGPT/Gemini занимают две строки рядом с заголовком и заходят в строку подзаголовка `together`; на `ru/desktop-1440x900/home.png` теснота аналогична. Нельзя назвать это доказанной полной невидимостью заголовка.
3. **Build Progress Planned/In Progress/Completed/Blocked:** **подтверждено в рамках первого экрана**. На `ru/desktop-1440x900/build-progress.png` и `en/mobile-390x844/build-progress.png` большой блок `Recent autonomous decisions` занимает экран, секция `LANES · VERIFIED EVENTS` / колонки статусов уходят ниже viewport. Скриншоты **не доказывают**, что колонки вообще недоступны при вертикальном прокручивании.

## Приоритетные исправления

| Приоритет / серьёзность | Точный скриншот | Что не так (наблюдение) | Как должно быть | Подсказка для Claude/CSS |
| --- | --- | --- | --- | --- |
| **P1 — заметно** | `ru/mobile-390x844/home.png`, `en/mobile-390x844/home.png` | Действия header растягивают строку за полезную ширину, правая часть `Share Viewer` уходит за край. | Все кнопки доступны без скрытого текста и без горизонтального скролла. | Верхняя панель `header/actions`: `min-width:0`, `flex-wrap:wrap`, компактное mobile-меню для Refresh/Share/New; убрать `nowrap` в группе при 390 px; отдельно проверить границы `getBoundingClientRect()`. |
| **P1 — заметно** | `ru/desktop-1440x900/build-progress.png`, `en/mobile-390x844/build-progress.png` | Длинный список последних решений получает основную высоту drawer до колонок workflow, которые нельзя увидеть в первом кадре. | На первом экране видны минимум числа Planned/In Progress/Completed/Blocked или быстрые вкладки к ним; логи раскрываются ниже. | В Build Progress перенести summary/lanes **выше** decision log; для лога `max-height` + `overflow-y:auto` или `<details>`, с доступными keyboard/focus controls. |
| **P1 — заметно** | `uk/desktop-1440x900/worker-center.png` | В украинской локали заголовки переведены, но основной T-506 runbook ("Привязать Telegram-бота владельца", "Токен бота ещё не добавлен...") на русском. | При выборе UK весь пользовательский runbook должен быть на украинском, коды/брендовые названия не переводятся. | В Worker Center / Owner Desk слой локализации runbook `why/steps/check/if`: создать locale-aware translations или явно обозначить fallback, добавить snapshot test каждой карточки по EN/UK/RU. |
| **P1 — заметно** | `en/desktop-1440x900/worker-center.png`, `en/mobile-390x844/worker-center.png` | EN оболочка ("Your tasks", "Ask Claude") содержит русскоязычные инструкции T-506; английский пользователь теряет последовательность шагов. | Цельный английский текст в EN. | Тот же translation adapter; проверка собственно текста карточек, а не только интерфейсной оболочки. |
| **P2 — заметно** | `en/desktop-1440x900/home.png`, `ru/desktop-1440x900/home.png` | Offline chips переносятся внутри Agent Office header, вторая строка оказывается на одной высоте с подзаголовком; визуальный ритм сломан. | Заголовок/подзаголовок и состояния агентов расположены в отдельных flex/grid зонах. | `Agent Office header`: `display:grid; grid-template-columns:minmax(0,1fr) auto`; для chips `flex-wrap:wrap` с выделенной строкой или горизонтальным scroll-container; проверить 1024 px. |
| **P2 — заметно** | `uk/tablet-1024x768/home.png`, `uk/tablet-1024x768/build-progress.png` | На 1024 px одновременно видны широкая sidebar, длинный main header и drawer; текст и цифры summary превращаются в мелкие узкие блоки; drawer практически вытесняет main area. | Drawer должен давать читаемую ширину, при этом навигация и кнопки управления остаются понятными. | `drawer`: адаптивные `width: clamp(...)`, `min-width`, `max-width`, breakpoint около tablet; уменьшить количество summary-карточек в строке, включить `grid-template-columns:repeat(2,minmax(0,1fr))`. |
| **P2 — заметно** | `ru/mobile-390x844/build-progress.png`, `en/mobile-390x844/build-progress.png` | Автономные решения отображаются сплошным мелким техническим англоязычным текстом даже в RU; большие абзацы плохо сканируются и вытесняют действия. | Краткие проверяемые status карточки с датой/типом, деталями по раскрытию; сообщения должны быть явно помечены как `raw worker evidence`, если не переводятся. | Нормализовать event card в компонентах build-progress, `line-clamp`/details, добавить `white-space:normal; overflow-wrap:anywhere`, RU/UK locale label. |
| **P3 — мелочь** | `ru/mobile-390x844/owner-desk-ask.png`, `uk/tablet-1024x768/owner-desk-ask.png` | Поле вопроса Claude поверх длинной инструкции занимает нижнюю часть drawer; не видно контекста выбранного шага при вводе. | В мини-диалоге — краткая ссылка/цитата текущего шага и видимый action, без закрытия основного контента. | Для owner-desk ask dialog — sticky caption `selected-step`, `max-height: min(70dvh,...)`, отдельный scroll для текста. **Нужно подтвердить в интерактивном браузере**, снимок не доказывает потерю функциональности. |

## Ограничения обзора

- PNG — одно состояние на сцену, не тесты интерактивных scroll/resize/focus/hit targets; если точный overflow касается локального элемента, нужно дополнительно сверить через браузер.
- Не проверены механизмы реакций CSS и ARIA на клавиатуре, реальные размеры шрифтов в CSS и рабочий production deployment.
- Текущая ветка main может измениться после 2026-11-01; при фиксе T-594–T-597 нужно повторить `ui-screenshots`, проверить все 54 файла и сравнить before/after.
- **Никакого изменения `static/index.html` здесь нет:** UI правит Claude Worker.

## Предлагаемые acceptance checks

- Mobile 390 px: все topbar actions видны или находятся в доступном overflow menu; `scrollWidth <= clientWidth` не только у `documentElement`, но и header controls.
- Agent Office 1440/1024/390: title/subtitle/chips не пересекаются; языковые строки не скрываются за controls.
- Build Progress: показатели/названия всех 4 lanes читаемы в верхней видимой части или доступны с одним явным действием; лог имеет ограниченную высоту.
- UK/EN/RU: `worker-center` runbooks полностью локализованы, а raw evidence явно обозначен.
