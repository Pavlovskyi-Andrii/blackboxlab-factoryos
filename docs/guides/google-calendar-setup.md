# Google Calendar for MyCast — owner setup (read-only access)

Goal: a listener presses "Підключити Google Календар" on the MyCast page, grants **read-only** access, and the
episode ends with today's meetings and friends' birthdays. Nothing is written to the calendar.

Code status: the connect button and OAuth flow are built only after steps 1–6 are done (they need the client secret).
Until then the page honestly shows "не підключено".

## Limits to know first (corrected after the Codex review on #332)
- **Publishing status and verification are two different things.** The status (*Testing* / *In production*) is set
  in Audience; verification is Google's review of the app.
  - *Testing*: only the test users you add (max 100) can connect, and **their Calendar access expires every 7 days**
    (Google issues 7-day refresh tokens to Testing apps that request sensitive scopes). Re-connecting weekly is
    expected, not a bug.
  - *In production* without verification: anyone can try, but they see an "unverified app" warning and Google caps the
    number of users who may grant the unverified sensitive scope.
  - *In production* and verified: no warning, no weekly expiry.
- **Status applies to the whole project.** If the project that holds the MyCast Google sign-in is already
  *In production*, do **not** switch it to *Testing*: everyone outside the test list would lose Google sign-in.
- Verification needs a **domain you own**: MyCast uses **mycast.pro** (bought 2026-11-13).

## Steps
1. **Project** — https://console.cloud.google.com → pick the project that holds the MyCast Google sign-in
   (the client behind `FACTORY_GOOGLE_CLIENT_ID`).
2. **Enable the API** — ☰ → APIs & Services → Library → "Google Calendar API" → Enable.
3. **Read-only scope** — ☰ → Google Auth Platform → Data Access → Add or remove scopes →
   `https://www.googleapis.com/auth/calendar.readonly` → Update → Save.
   This covers meetings and Google's "Birthdays" calendar.
4. **Redirect URI** — Google Auth Platform → Clients → the *Web application* client → Authorized redirect URIs →
   add `https://mycast.pro/api/mycast/calendar/callback` (and, for the old address,
   `https://blackboxlab-factoryos.onrender.com/api/mycast/calendar/callback`). In **Authorized JavaScript origins**
   add `https://mycast.pro` (Google sign-in on the new domain). Save.
5. **Client secret on Render** — in the same client copy *Client secret* (or *Add secret*) → Render → service
   `blackboxlab-factoryos` → Environment → `FACTORY_GOOGLE_CLIENT_SECRET` → Save. Never paste it into chat or Git.
6. **Test users** — Google Auth Platform → Audience. Only if the status is already *Testing*: Test users → add up to
   100 Gmail addresses. If it is *In production*, leave it as it is (see the limits above).
7. **Branding** — Google Auth Platform → Branding: app name (MyCast), support email, home page `https://mycast.pro`,
   privacy policy `https://mycast.pro/privacy`, terms `https://mycast.pro/terms`, authorized domain `mycast.pro`.
8. **Verification (with the own domain)** — verify the domain in Google Search Console, then Google Auth Platform →
   Verification Center → submit: a short video showing the consent screen and how calendar data is used, and the
   reason for `calendar.readonly` ("read today's events and birthdays to read them out in the listener's personal
   audio episode; nothing is stored or shared").

When steps 1–6 are done, tell Claude "готово": the connect button, OAuth flow and the calendar segment are built next.
