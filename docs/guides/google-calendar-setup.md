# Google Calendar for MyCast — owner setup (read-only access)

Goal: a listener presses "Підключити Google Календар" on the MyCast page, grants **read-only** access, and the
episode ends with today's meetings and friends' birthdays. Nothing is written to the calendar.

Code status: the connect button and OAuth flow are built only after steps 1–6 are done (they need the client secret).
Until then the page honestly shows "не підключено".

## Limits to know first
- Without Google verification, at most **100 test users** you add by hand can connect, and they see an
  "unverified app" warning.
- Verification needs a **domain you own** (an `…onrender.com` address cannot be verified). Plan the MyCast domain first.

## Steps
1. **Project** — https://console.cloud.google.com → pick the project that holds the MyCast Google sign-in
   (the client behind `FACTORY_GOOGLE_CLIENT_ID`).
2. **Enable the API** — ☰ → APIs & Services → Library → "Google Calendar API" → Enable.
3. **Read-only scope** — ☰ → Google Auth Platform → Data Access → Add or remove scopes →
   `https://www.googleapis.com/auth/calendar.readonly` → Update → Save.
   This covers meetings and Google's "Birthdays" calendar.
4. **Redirect URI** — Google Auth Platform → Clients → the *Web application* client → Authorized redirect URIs →
   add `https://blackboxlab-factoryos.onrender.com/api/mycast/calendar/callback` (and the same path on the MyCast
   domain once it is connected) → Save.
5. **Client secret on Render** — in the same client copy *Client secret* (or *Add secret*) → Render → service
   `blackboxlab-factoryos` → Environment → `FACTORY_GOOGLE_CLIENT_SECRET` → Save. Never paste it into chat or Git.
6. **Test users** — Google Auth Platform → Audience → status *Testing* → Test users → add up to 100 Gmail addresses.
7. **Branding** — Google Auth Platform → Branding: app name (MyCast), support email, home page, privacy policy and
   terms links, authorized domain (your MyCast domain).
8. **Verification (with the own domain)** — verify the domain in Google Search Console, then Google Auth Platform →
   Verification Center → submit: a short video showing the consent screen and how calendar data is used, and the
   reason for `calendar.readonly` ("read today's events and birthdays to read them out in the listener's personal
   audio episode; nothing is stored or shared").

When steps 1–6 are done, tell Claude "готово": the connect button, OAuth flow and the calendar segment are built next.
