# OAuth-підключення у FactoryOS

Цей документ описує архітектуру та процес OAuth 2.0 підключення зовнішніх акаунтів (YouTube, TikTok, Instagram, HubSpot) до FactoryOS (T-551).

## 1. Як влаштоване підключення соцмереж

Підключення акаунтів соцмереж виконується за протоколом OAuth 2.0 (з підтримкою PKCE RFC 7636 для провайдерів, які підтримують цей стандарт):

### Крок 1. Ініціалізація авторизації (`OAuthFlow.start`)
- Користувач запитує посилання авторизації для провайдера (наприклад, YouTube або Instagram).
- Система перевіряє наявність конфігурації (`Client ID`) і відсутність блокерів (готовність адаптера та `TokenVault`).
- Генерується захисний одноразовий параметр `state` і (якщо PKCE увімкнено) `code_verifier` / `code_challenge`.
- Користувача перенаправляють на зовнішню сторінку авторизації провайдера (`authorize_url`).

### Крок 2. Авторизація власником акаунта
- Користувач підтверджує доступ до запитуваних дозволів (`scopes`) в інтерфейсі провайдера.
- Провайдер перенаправляє браузер на `redirect_uri` FactoryOS (`/api/oauth/{provider}/callback`) з кодом авторизації (`code`) і раніше переданим `state`.

### Крок 3. Завершення підключення (`OAuthFlow.complete`)
- FactoryOS перевіряє дійсність і строк дії `state`.
- Адаптер провайдера (`OAuthAdapter`) обмінює `code` на токени доступу (`access_token`, `refresh_token`).
- Токени зберігаються у сховищі (`TokenVault`). Секрети ніколи не передаються в публічних API-відповідях.

### Крок 4. Відключення акаунта (`OAuthFlow.disconnect`)
- Виконується спроба відкликати права (`revoke`) на боці провайдера і локально видалити токени з `TokenVault`.
- Історія контенту та публікацій у FactoryOS повністю зберігається.

## 2. Навіщо потрібен параметр `state`

Параметр `state` — це випадковий одноразовий токен, який сервер FactoryOS створює під час запуску авторизації:

- **Захист від CSRF-атак**: гарантує, що зворотний виклик авторизації (callback) ініціював саме поточний користувач і в межах тієї самої сесії.
- **Зв'язування контексту**: зберігає прив'язку до робочого простору (`workspace`), провайдера та ініціатора запиту (`subject`).
- **Безпека та час життя (TTL)**:
  `state` одноразовий і видаляється одразу під час виклику `consume`.
  Має обмежений строк життя (`STATE_TTL_SECONDS = 600`, тобто 10 хвилин).
  У пам'яті сервер підтримує ліміт активних очікуваних авторизацій (`MAX_PENDING_STATES = 200`).

## 3. Що потрібно від власника системи (T-551)

Щоб увімкнути OAuth-інтеграції в продакшені, власник системи має зареєструвати OAuth 2.0 застосунки в консолях розробника відповідних сервісів і задати змінні оточення.

### Налаштування Redirect URI в консолях провайдерів

У налаштуваннях застосунків потрібно додати Redirect URI у форматі:
`https://<your-domain>/api/oauth/<provider_id>/callback`

Приклади:
- Google / YouTube: `https://<your-domain>/api/oauth/youtube/callback`
- TikTok: `https://<your-domain>/api/oauth/tiktok/callback`
- Meta / Instagram: `https://<your-domain>/api/oauth/instagram/callback`
- HubSpot: `https://<your-domain>/api/oauth/hubspot/callback`

### Змінні оточення (Environment Variables)

Власник задає такі ключі в оточенні сервера (без збереження секретів у репозиторії):

- **Google / YouTube**: `FACTORY_OAUTH_GOOGLE_CLIENT_ID`, `FACTORY_OAUTH_GOOGLE_CLIENT_SECRET`
- **TikTok**: `FACTORY_OAUTH_TIKTOK_CLIENT_KEY`, `FACTORY_OAUTH_TIKTOK_CLIENT_SECRET`
- **Meta / Instagram**: `FACTORY_OAUTH_META_APP_ID`, `FACTORY_OAUTH_META_APP_SECRET`
- **HubSpot**: `FACTORY_OAUTH_HUBSPOT_CLIENT_ID`, `FACTORY_OAUTH_HUBSPOT_CLIENT_SECRET`

> **Примітка**: доки не реалізовано повноцінні адаптери та зашифрований токен-волт (T-552), методи авторизації повертають відповідний статус блокера (`vault_unavailable`, `adapter_missing` або `client_not_configured`, якщо ключі провайдера не задано).
