# T-551 / T-552 — OAuth provider research for FactoryOS

**Проверено по публичной документации: 2026-11-01; Issue #87.** Не создавались приложения, OAuth-клиенты, токены, платные ресурсы или реальные публикации. Это **техническая разведка** для реализации T-552, а не свидетельство прохождения провайдерских ревью.

Планируемые callback URL:
- YouTube: `https://blackboxlab-factoryos.onrender.com/api/integrations/google/oauth/callback`
- TikTok: `https://blackboxlab-factoryos.onrender.com/api/integrations/tiktok/oauth/callback`
- Instagram: `https://blackboxlab-factoryos.onrender.com/api/integrations/instagram/oauth/callback`
- HubSpot: `https://blackboxlab-factoryos.onrender.com/api/integrations/hubspot/oauth/callback`

Эти адреса **не являются работающими endpoints**, пока T-552 не реализует обработчик, `state`, обмен и безопасное хранение токенов. В рабочем issue использован плейсхолдер `{provider}`: подставлять фактический код провайдера без фигурных скобок.

## 1. Google Cloud / YouTube Data API v3

| Вопрос | Проверенный факт / ограничение | Статус и ссылка |
| --- | --- | --- |
| Консоль и тип | Google Cloud Console → APIs & Services → Credentials; OAuth client типа **Web application**; включить YouTube Data API v3, настроить OAuth consent screen / Google Auth Platform. | [из документации: https://developers.google.com/youtube/data/guides/auth/server-side-web-apps, 2026-11-01] |
| Минимальный scope для видео | `https://www.googleapis.com/auth/youtube.upload`. Для чтения профиля/канала: `https://www.googleapis.com/auth/youtube.readonly`. Для чтения статистики YouTube Analytics API отдельно `https://www.googleapis.com/auth/yt-analytics.readonly`; не просить полный `youtube` без причины. | [из документации: https://developers.google.com/youtube/data/guides/auth/server-side-web-apps, 2026-11-01] |
| Consent / review | При публичном использовании чувствительных/restricted scopes может требоваться OAuth app verification; не считать тестовый consent производственным разрешением. Новые неаудированные проекты YouTube Data API с 28.07.2020 ограничены **private-only** для `videos.insert` до compliance audit. | [из документации: https://developers.google.com/youtube/data/revision_history, 2026-11-01]; [из документации: https://developers.google.com/youtube/data/guides/auth/server-side-web-apps, 2026-11-01] |
| До ревью | Можно проектировать OAuth, использовать тестовых пользователей при допустимой конфигурации consent; публиковать публично через новый неаудированный клиент **нельзя считать доступным**. | [из документации: https://developers.google.com/youtube/data/revision_history, 2026-11-01] |
| Redirect URI | Строка в настройках OAuth client должна **точно совпадать** со схемой/регистром/path/trailing slash. HTTPS Render URL подходит **синтаксически**, если зарегистрирован. localhost HTTP используется в примерах для разработки. Несколько URI — в списке Authorized redirect URIs; точный лимит списка не проверялся. | [из документации: https://developers.google.com/youtube/data/guides/auth/server-side-web-apps, 2026-11-01] |
| Tokens | Для refresh token требуется `access_type=offline`, сохранять server-side. Точное время жизни token/refresh зависит от consent и политик; учитывать refresh, revoke и тестовый режим — не кодировать без проверки. | [из документации: https://developers.google.com/youtube/data/guides/auth/server-side-web-apps, 2026-11-01]; [не проверено: фактическая политика будущего приложения] |
| Quota / цена | YouTube Data API даёт по умолчанию 100 `videos.insert`/day, 100 `search.list`/day, 10 000 units для остальных endpoints; квоты могут меняться. Дополнительная квота требует compliance audit. Платное Cloud API billing не включать. | [из документации: https://developers.google.com/youtube/data/determine_quota_cost, 2026-11-01]; [из документации: https://developers.google.com/youtube/data/guides/quota_and_compliance_audits, 2026-11-01] |
| Владелец / сроки | Владельцу нужен Google Account, разрешения канала и consent-app сведения (домен, политики при требовании review); сроки проверки/нужность business verification **не подтверждены** для данного клиента. | [не проверено] |

## 2. TikTok Login Kit + Content Posting API

| Вопрос | Проверенный факт / ограничение | Статус и ссылка |
| --- | --- | --- |
| Консоль | https://developers.tiktok.com/ → **Manage apps** → создать developer app; добавить **Login Kit** и **Content Posting API**, настроить Direct Post отдельно. | [из документации: https://developers.tiktok.com/docs/en/login-kit-web, 2026-11-01]; [из документации: https://developers.tiktok.com/docs/en/content-posting-api-get-started, 2026-11-01] |
| Scopes | Профиль: `user.info.basic` (доп. поля при необходимости `user.info.profile`); публичные видео: `video.list`; загрузка черновика/inbox: `video.upload`; прямой пост: `video.publish`. Права должны быть одобрены для app и выданы пользователем. | [из документации: https://developers.tiktok.com/docs/en/tiktok-api-scopes, 2026-11-01]; [из документации: https://developers.tiktok.com/docs/en/content-posting-api-get-started, 2026-11-01] |
| Статистика | `user.info.stats` для агрегированной статистики профиля; `video.list` для доступных полей публичных видео. Полный доступ к аналитике конкретного видео и специальные scopes — **не подтверждены**, не обещать. | [из документации: https://developers.tiktok.com/docs/en/tiktok-api-scopes, 2026-11-01]; [не проверено: полнота пост-аналитики] |
| Audit / до ревью | Клиент без TikTok audit может отправлять Direct Post только **private**; нужен аудит для публичного контента. До него использовать тестирование в пределах допуска, не запускать публикацию без owner approval. Типичный срок ревью не опубликован в проверенном документе. | [из документации: https://developers.tiktok.com/docs/en/content-posting-api-get-started, 2026-11-01]; [не проверено: срок] |
| Redirect URI | Для **web** — абсолютный статический **HTTPS**, без query/fragment, до 10 URI, каждый менее 512 символов; proposed Render URL подходит синтаксически при регистрации. HTTP localhost допускается для **desktop** типа приложения, не для Web Login Kit. | [из документации: https://developers.tiktok.com/docs/en/login-kit-web, 2026-11-01]; [из документации: https://developers.tiktok.com/docs/en/login-kit-desktop, 2026-11-01] |
| Tokens | Access token ~**24 часа**, refresh token ~**365 дней**; refresh может возвращать новый refresh token, заменять атомарно. | [из документации: https://developers.tiktok.com/docs/en/oauth-user-access-token-management, 2026-11-01] |
| Лимиты | Инициализация Direct Post ограничена **6 запросами/мин на access token**; для inbox upload — также 6/мин и максимум 5 ожидающих публикаций за 24ч в соответствующем сценарии. У отдельного приложения могут быть другие лимиты. | [из документации: https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post, 2026-11-01]; [из документации: https://developers.tiktok.com/docs/en/content-posting-api-reference-upload-video, 2026-11-01] |
| Домен/публичные страницы | При `PULL_FROM_URL` нужно подтвердить владение domain/URL prefix медиа; наличие пригодной privacy policy / ToS / business-verification в будущем TikTok review пока не сверено по конкретной app. | [из документации: https://developers.tiktok.com/docs/en/content-posting-api-get-started, 2026-11-01]; [не проверено: review checklist] |
| Цена | Платный тариф для самого Content Posting API в проверенных источниках не указан; возможные внешние затраты на медиа-хостинг/верификацию **не оценены**. Не утверждать «бесплатно без ограничений». | [не проверено] |

## 3. Meta / Instagram API

**Рекомендуемый первый вариант**: Instagram API with Instagram Login для Business/Creator; не смешивать с Facebook Login, у них разные scopes и требования. Ссылки на официальную документацию и официальную коллекцию **Meta на Postman**.

| Вопрос | Проверенный факт / ограничение | Статус и ссылка |
| --- | --- | --- |
| Консоль/продукт | https://developers.facebook.com/apps → создать Meta app с Instagram use case; выбрать **Instagram API with Instagram Login**. Альтернатива **Instagram API with Facebook Login** нужна при связке с Page. | [из документации: https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api, 2026-11-01] |
| Instagram Login scopes | Профиль: `instagram_business_basic`; публикация Reels: `instagram_business_content_publish`; аналитика: `instagram_business_manage_insights` (проверить наличие и review в текущих настройках); не добавлять comments/messages без нужды. | [из документации: https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login, 2026-11-01]; [не проверено: актуальный порядок review для insights] |
| Facebook Login scopes (альтернатива) | Для профиля/Page: `instagram_basic`, `pages_show_list`, `pages_read_engagement`; для Reels `instagram_content_publish`; для insights `instagram_manage_insights`. Требуется Instagram Professional, связанный с Facebook Page. | [из документации: https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api, 2026-11-01] |
| Meta App Review | Для пользователей за пределами ролей приложения обычно потребуется Advanced Access/App Review на требуемые permissions; подготовить запись экранного OAuth-flow и демонстрацию разрешённых функций. Точный список бизнес-верификаций и срок решения зависит от use-case — **не проверен в будущей app**. | [из документации: https://developers.facebook.com/docs/app-review, 2026-11-01]; [не проверено: сроки/текущий статус] |
| До ревью | Разработчик/tester с соответствующей ролью может тестировать в Development Mode в допустимых пределах; доступ внешним пользователям и продакшн-публикация **не подтверждены**. | [не проверено: фактический режим и роли приложения] |
| Redirect | `https://.../api/integrations/instagram/oauth/callback` выглядит правильным HTTPS URL; обязательно внести exact callback в валидные OAuth redirect URIs продукта и проверить через живую console. Количество допустимых URI/localhost зависит от выбранного Login продукта и здесь не подтверждено. | [не проверено: регистрация и validation в Meta Developer console] |
| Контент | Для Reels публикация происходит через создание media container → publish; видео должно быть доступно Meta по публичному URL. Квоту читать через `/{ig-user-id}/content_publishing_limit`, поскольку публичные цифры документов противоречат друг другу (50/100 за 24ч). | [из документации: https://developers.facebook.com/docs/instagram-platform/content-publishing, 2026-11-01]; [из документации: https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/content_publishing_limit, 2026-11-01] |
| Токены / цена | Конкретный срок long-lived token/refresh для выбранного Login, список обязательных публичных privacy/ToS и возможные расходы Meta Business Verification: **не проверено**. До реализации выбрать flow и подтвердить в консоли, не hardcode 60 дней. | [не проверено] |

## 4. HubSpot Developer Platform (CRM, **не** видео-публикатор)

| Вопрос | Проверенный факт / ограничение | Статус и ссылка |
| --- | --- | --- |
| Консоль/тип | https://developers.hubspot.com/ → **Projects-based developer app**, OAuth для подключения разных customer portals; legacy public app creation отключена в 2026. Для собственных S2S задач без OAuth доступны Service Keys, но они не заменяют multi-tenant OAuth. | [из документации: https://developers.hubspot.com/changelog/legacy-public-app-creation-sunset, 2026-11-01]; [из документации: https://developers.hubspot.com/changelog/service-keys, 2026-11-01] |
| Scopes | Для демонстрации CRM достаточно `crm.objects.contacts.read`, при необходимости `crm.objects.companies.read` и аналогичных granular read scopes. **Видео-публикация в TikTok/Instagram/YouTube через HubSpot OAuth не предусмотрена** в проверенном контракте CRM; не придумывать `video.publish` scope для HubSpot. | [из документации: https://developers.hubspot.com/changelog/additional-details-returned-when-generating-oauth-access-tokens, 2026-11-01]; [из документации: https://developers.hubspot.com/blog/build-with-confidence-app-governance, 2026-11-01]; [не проверено: наличие специализированных social-publishing endpoints] |
| Профиль/статистика | CRM identity/portal ID доступны в OAuth token response; CRM объекты/маркетинг и аналитика — только с конкретными scopes и доступным продуктом, а не с Instagram/TikTok scopes. | [из документации: https://developers.hubspot.com/changelog/additional-details-returned-when-generating-oauth-access-tokens, 2026-11-01] |
| Marketplace review | Для локальной установки unverified app возможен warning с явным подтверждением риска; для Marketplace listing отдельная сертификация. Точный срок и eligibility Project app не проверены. | [из документации: https://developers.hubspot.com/docs/guides/apps/public-apps/overview, 2026-11-01]; [не проверено: новый Projects workflow и сроки] |
| Redirect | Конфигурируется в OAuth app, `redirect_uri` должен быть согласован с установленным URL; HTTPS Render callback подходит как план. Старые docs допускают `http://localhost` при разработке, **не переносить** этот факт без проверки на новый Projects OAuth. | [из документации: https://developers.hubspot.com/docs/guides/apps/public-apps/overview, 2026-11-01]; [не проверено: new Projects validation] |
| Tokens | OAuth access token response содержит `expires_in: 1800` (30 минут) и refresh token; хранить отдельно по portal/installation; обновлять через token endpoint, поддерживать revoke/uninstall. | [из документации: https://developers.hubspot.com/changelog/additional-details-returned-when-generating-oauth-access-tokens, 2026-11-01]; [из документации: https://developers.hubspot.com/blog/oauth-token-management-hubspot-integrations, 2026-11-01] |
| Rate limits / платные уровни | Значения rate limit, дневные квоты и CRM-функции, требующие Hub subscription tier, зависят от portal/app/endpoint; для будущего приложения **не проверены**. Создание Developer app само по себе не означает включения платных функций. | [не проверено] |
| Требования владельца | HubSpot developer access и разрешения аккаунта; не создавать старую legacy public app. Для публичного Marketplace listing проверить privacy policy / terms, домен и review требования отдельно. | [из документации: https://developers.hubspot.com/changelog/legacy-public-app-creation-sunset, 2026-11-01]; [не проверено: Marketplace checklist] |

## Рекомендуемый порядок работ и то, что можно сделать сейчас

1. **Сейчас, без платежей/токенов:** выделить неизменные callback paths; приготовить черновик privacy policy / terms и поддержку удаления данных/отключения интеграций. Не объявлять документацию юридически готовой.
2. **Google/YouTube** — начать OAuth client + review/audit planning первым из video channels; основной риск private-only до YouTube audit. Создать проект без платного billing только при одобрении владельца и проверенной политике нулевых затрат.
3. **TikTok** — Login Kit + `video.upload` draft first, `video.publish` только после product/scope review и явного approval поста; решить проверку владения доменом media.
4. **Instagram** — сначала установить Business/Creator status, выбрать Instagram Login vs Facebook Login, зарегистрировать use case и проверить App Review.
5. **HubSpot** — отдельно как CRM customer-integration, не замена видео-сетям. Для нового публичного multi-tenant приложения использовать Projects-based OAuth, не legacy UI.

### Контракт для Claude (T-552)

- Один провайдер/installation/workspace → отдельные `state`, доступы, шифрованные credentials, atomically rotated refresh token, revoke/disconnect.
- Перед редиректом сверять allowlisted URI и подтверждение пользователя; в callback валидировать `state`, код и provider, не логировать query params с `code`.
- Не пытаться публиковать до завершения ревью + явного owner approval exact immutable snapshot. `oauth.connected` **не равен** `publisher.ready`.
- В каждом подключении показывать `scopes granted`, `review status: unverified` если отсутствует свидетельство, expiry, последнюю read-only проверку и блокер.
- Для неизвестных пунктов выше поставить технический вопрос к провайдеру или проверить в Developer Console при создании приложения; **не объявлять верификацию завершённой**.

Проверенные ссылки относятся к публичным документам на дату аудита, а не к конкретным созданным приложениям (их ещё нет).
