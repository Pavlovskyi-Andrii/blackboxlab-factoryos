# OAuth-подключения в FactoryOS

Данный документ описывает архитектуру и процесс OAuth 2.0 подключения внешних аккаунтов (YouTube, TikTok, Instagram, HubSpot) к FactoryOS (T-551).

## 1. Как устроено подключение соцсетей

Подключение аккаунтов соцсетей выполняется по протоколу OAuth 2.0 (с поддержкой PKCE RFC 7636 для провайдеров, поддерживающих данный стандарт):

1. **Инициализация авторизации (`OAuthFlow.start`)**:
   - Пользователь запрашивает ссылку авторизации для провайдера (например, YouTube или Instagram).
   - Система проверяет наличие конфигурации (`Client ID`) и отсутствие блокеров (готовность адаптера и `TokenVault`).
   - Генерируется защитный одноразовый параметр `state` и (при включенном PKCE) `code_verifier` / `code_challenge`.
   - Пользователь перенаправляется на внешнюю страницу авторизации провайдера (`authorize_url`).

2. **Авторизация владельцем аккаунта**:
   - Пользователь подтверждает доступ к запрашиваемым разрешениям (`scopes`) в интерфейсе провайдера.
   - Провайдер перенаправляет браузер на `redirect_uri` FactoryOS (`/api/oauth/{provider}/callback`) с кодом авторизации (`code`) и ранее переданным `state`.

3. **Завершение подключения (`OAuthFlow.complete`)**:
   - FactoryOS проверяет валидность и срок действия `state`.
   - Адаптер провайдера (`OAuthAdapter`) обменивает `code` на токены доступа (`access_token`, `refresh_token`).
   - Токены сохраняются в хранилище (`TokenVault`). Секреты никогда не передаются в публичных API-ответах.

4. **Отключение аккаунта (`OAuthFlow.disconnect`)**:
   - Выполняется попытка отзыва прав (`revoke`) на стороне провайдера и локальное удаление токенов из `TokenVault`.
   - История контента и публикаций в FactoryOS полностью сохраняется.

## 2. Зачем нужен параметр `state`

Параметр `state` — это случайный одноразовый токен, создаваемый сервером FactoryOS при запуске авторизации:

- **Защита от CSRF-атак**: гарантирует, что ответный вызов авторизации (callback) был инициирован именно текущим пользователем и в рамках той же сессии.
- **Связывание контекста**: сохраняет привязку к рабочему пространству (`workspace`), провайдеру и инициатору запроса (`subject`).
- **Безопасность и время жизни (TTL)**:
  - `state` является одноразовым и удаляется сразу при вызове `consume`.
  - Имеет ограниченный срок жизни (`STATE_TTL_SECONDS = 600`, т.е. 10 минут).
  - В памяти сервером поддерживается лимит активных ожидания авторизаций (`MAX_PENDING_STATES = 200`).

## 3. Что требуется от владельца системы (T-551)

Для включения OAuth-интеграций в продакшене владелец системы должен зарегистрировать OAuth 2.0 приложения в разработческих консолях соответствующих сервисов и задать переменные окружения.

### Настройка Redirect URI в консолях провайдеров

В настройках приложений необходимо добавить Redirect URI формата:
`https://<your-domain>/api/oauth/<provider_id>/callback`

Примеры:
- Google / YouTube: `https://<your-domain>/api/oauth/youtube/callback`
- TikTok: `https://<your-domain>/api/oauth/tiktok/callback`
- Meta / Instagram: `https://<your-domain>/api/oauth/instagram/callback`
- HubSpot: `https://<your-domain>/api/oauth/hubspot/callback`

### Переменные окружения (Environment Variables)

Владелец задает следующие ключи в окружении сервера (без сохранения секретов в репозитории):

- **Google / YouTube**:
  - `FACTORY_OAUTH_GOOGLE_CLIENT_ID`
  - `FACTORY_OAUTH_GOOGLE_CLIENT_SECRET` me

- **TikTok**:
  - `FACTORY_OAUTH_TIKTOK_CLIENT_KEY`
  - `FACTORY_OAUTH_TIKTOK_CLIENT_SECRET`

- **Meta / Instagram**:
  - `FACTORY_OAUTH_META_APP_ID`
  - `FACTORY_OAUTH_META_APP_SECRET`

- **HubSpot**:
  - `FACTORY_OAUTH_HUBSPOT_CLIENT_ID`
  - `FACTORY_OAUTH_HUBSPOT_CLIENT_SECRET`

*Примечание: До реализации полноценных адаптеров и шифрованного токен-волта (T-552) методы авторизации возвращают соответствующий статус блокера (`vault_unavailable` или `adapter_missing`).*
