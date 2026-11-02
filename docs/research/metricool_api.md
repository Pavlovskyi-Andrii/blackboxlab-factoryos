# T-520 · Metricool API — проверка для FactoryOS

Дата аудита: 2026-11-01. Issue: #86. **Никакой оплаты, перевода тарифа или публикации не выполнено.**

## Таблица: факт → пометка → источник

| Факт / решение | Пометка | Источник |
| --- | --- | --- |
| В подключённом Metricool доступен бренд `blackboxlab7`; подключены Instagram `blackboxlab7`, TikTok `@blackboxlab`, YouTube. | **[проверено в аккаунте, 2026-11-01]** (read-only вызов официального Metricool MCP `getBrandSettings`) | Metricool MCP / brand settings (авторизованный ответ, без секретов) |
| Для этого бренда Metricool MCP возвращает отдельные числовые `userId` и ID бренда (`blogId`). Точные значения не публикуем: владельцу удобнее смотреть их в собственном кабинете. | **[проверено в аккаунте, 2026-11-01]** | Metricool MCP / brand settings |
| Текущий тариф **именно этого аккаунта** (Free / Starter / Advanced / Custom). `getBrandSettings` тарифа не показывает; кабинет Billing не открывался. | **[не проверено]** | Проверить вручную: Account settings → Plans and billing |
| Путь к тарифу: верхнее меню `☰` → **Account settings** → **Plans and billing**. | **[из документации: https://help.metricool.com/manage-your-account-settings-lgz76, 2026-11-01]** | Metricool Help |
| Доступ к server-side Metricool API включён только для **Advanced / Custom**; **Free / Starter не подходят**. Наличие MCP-подключения в ChatGPT **не означает** доступа к внешнему API FactoryOS. | **[из документации: https://help.metricool.com/plans-add-ons-and-api-access-explained-xux1u, 2026-11-01]** | Metricool Help |
| Путь к API-токену: **Account settings → API → Access token**; эта вкладка доступна на соответствующем плане. Значение секретное: не вставлять в чат, issue, PR или файлы репозитория. | **[из документации: https://help.metricool.com/basic-guide-for-api-integration-r97af, 2026-11-01]** | Metricool Help |
| `userId` и `blogId`: в веб-кабинете откройте бренд и найдите в URL `?blogId=...&userId=...`; `blogId` — бренд, `userId` — пользователь. Не искать `userId` в поле токена. | **[из документации: https://help.metricool.com/how-to-find-your-metricool-user-id-fabrt, 2026-11-01]** | Metricool Help |
| Запросы REST API используют `X-Mc-Auth` с токеном, а также параметры `userId` и `blogId`. | **[из документации: https://help.metricool.com/basic-guide-for-api-integration-r97af, 2026-11-01]** | Metricool Help |
| Начальная публичная цена Advanced: **от $53/мес** при годовой оплате или **от $67/мес** при помесячной, до 15 брендов; возможны налоги и региональные различия. Это **не согласование покупки**. | **[из документации: https://metricool.com/premium-vs-free-metricool-plans/, 2026-11-01]** | Metricool |
| Планировщик Metricool поддерживает YouTube Shorts (вертикальное/квадратное до 3 минут); автоматическую публикацию YouTube. | **[из документации: https://help.metricool.com/schedule-and-publish-on-youtube-gof0k, 2026-11-01]** | Metricool Help |
| Планировщик Metricool поддерживает авто-публикацию TikTok (если включён `AUTO PUBLISH`, с ограничениями аудио/эффектов). | **[из документации: https://help.metricool.com/schedule-and-post-on-tiktok-bkepi, 2026-11-01]** | Metricool Help |
| Планировщик Metricool поддерживает Instagram Reels для профессиональных аккаунтов (Business/Creator), но часть функций требует ручного завершения. | **[из документации: https://help.metricool.com/schedule-and-post-on-instagram-6b6q5, 2026-11-01]** | Metricool Help |
| Конкретные REST API endpoints / формат payload для всех трёх типов публикаций **на живом аккаунте** не проверялись: отсутствует подтверждённый API-тариф/токен. Поддержка планировщика ≠ испытанная REST-интеграция. | **[не проверено]** | После разрешённого доступа — сверить https://app.metricool.com/resources/apidocs/index.html, сделать только безопасный read-only запрос |
| Лимиты *публикаций* Metricool: Instagram **50 / 24 ч**; YouTube Free **10 / 24 ч**, paid **20 / 24 ч**. TikTok: точный числовой лимит здесь не опубликован. | **[из документации: https://help.metricool.com/daily-posting-limits-on-social-media-sh58j, 2026-11-01]** | Metricool Help |
| Лимит *REST API-запросов* Metricool (calls/minute, calls/day) зависит от доступной документации/тарифа; точного числа в проверенных публичных статьях не найдено, его **нельзя выдумывать**. | **[не проверено]** | Уточнить в Account settings → API → usage / https://app.metricool.com/resources/apidocs/index.html |
| Доступность токена в аккаунте и корректность сервера `FACTORY_METRICOOL_*` **не проверялись**. | **[не проверено]** | Только владелец может проверить UI без раскрытия секретов; серверный статус `metricool_configured` после явного разрешения |

## Исправление инструкции Owner Desk

- Шаг `plan`: сначала выяснить тариф в **Plans and billing**, потом открыть **API**; не считать наличия MCP достаточным для REST API. Если Free/Starter — **остановиться**, не повышать тариф.
- Шаг `ids`: оба числа берутся из адресной строки `blogId=...&userId=...`, а API-токен — отдельно через **Account settings → API**.
- Сохранены имена конфигурационных переменных: `FACTORY_METRICOOL_TOKEN`, `FACTORY_METRICOOL_USER_ID`, `FACTORY_METRICOOL_BLOG_ID`, `FACTORY_PUBLISHER_ADAPTER`, `FACTORY_METRICOOL_YOUTUBE_MADE_FOR_KIDS`.

## Блокировка и next step

**Не включать платный API** для завершения T-520 без отдельного согласия владельца. Возможен путь через подключённый Metricool MCP внутри ChatGPT, но он **не является** автоматически доступным серверным publisher adapter: для FactoryOS потребуется отдельный технический и безопасностный проект с неизменяемым snapshot и обязательным явным approval. Ручная публикация остаётся разрешённой альтернативой **только после явного approval каждого поста**.

### Что остаётся неизвестным

Аккаунтный тариф; API-токен/доступ; REST rate limits; совместимость каждого REST-эндпоинта с текущим кодом; реальная доставка поста. Эти пункты **не отмечены готовыми**.
