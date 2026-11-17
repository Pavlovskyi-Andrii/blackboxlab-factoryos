# MyCast: library, public links and the episode page

A short beginner guide: where a listener sees their episodes, how to share one episode, and what a person with the link will see.

## What it is

- **The "My podcasts" library** is the list of a listener's episodes in their cabinet on the `/mycast` page (after signing in with Telegram or Google).
- **A public link** is an address like `/mycast/e/<token>` that opens one chosen episode without signing in.
- **The episode page** is what the link's recipient sees: cards, a player and the "About this podcast" block.

## The library

- Only an episode that really reached the listener's Telegram goes into the library. The newest 200 episodes are kept.
- The server stores Telegram's `file_id`, not the audio file. The cabinet player fetches the sound from Telegram through the server; the bot token stays on the server.
- States are honest: ready to play, "Audio unavailable", "Being prepared…", "Could not be made".

## How to share an episode

1. Open "My podcasts" and find an episode with a player.
2. Tick "Public link". An address and a "Share" button appear.
3. Send the link yourself: FactoryOS posts nothing anywhere and notifies nobody.
4. To close access, untick the box. The link stops working at once; turning it on again creates a new link.

## How the link works

- The link is not signed and has no expiry. It is a random 16-character token that cannot be guessed.
- The link works until the author turns it off or deletes the account.
- An episode without audio cannot be published: there is nothing to share.
- The page is served with `noindex`, `no-store` and `no-referrer`: search engines do not index it, and no cache keeps an old copy.
- One link can be played up to 60 times an hour; after that the server answers `429`.

## What a stranger sees

| Visible | Never visible |
|---|---|
| episode title, date, length | chat id, e-mail |
| the author's name (first word only) | slug and settings code |
| a player for this episode | `file_id` and other episodes |
| topics, category mix, geography (Ukraine / World) | accounts the author follows |
| schedule, voice mode and language | the author's own free-text topics, own city |

## Cards on the episode page

- **The first card, "The author's episode"**: a cover drawn from the author's topics, the title, "{name}'s podcast", date, minutes, one or two hosts, and a "Listen" button.
- **Demo cards** about ancient cities: Athens, Rome, Delphi, Olympia, Pompeii. They show how the hosts sound and are not part of the author's podcast.
- At the bottom is a player bar, below it the "About this podcast" block. Cards move by swipe, arrows or keyboard. Page language: RU / UK / EN.

## Voices and delivery in brief

- The configurator has 30 Gemini voices with real samples; the voice gender is judged by ear, unofficially.
- Mode: one narrator or two hosts; language: Ukrainian, Russian or English.
- An episode goes only to the listener's own Telegram chat, and only after profile approval, a test message and consent. The shared limit is 10 listener episodes per day (UTC).

## Limits

- The demo episodes are not approved by the owner yet (task T-645-H), so the demo cards say "Soon" and have no play button.
- Invite bonuses stay hidden until the owner decides (T-620-H), and the free period does not limit delivery yet.
- If Telegram is not configured on the server, the sound behind a link does not play.
- There is also a separate page for the whole podcast, `/mycast/u/<slug>`: its latest episode plays only if the listener turned on listening by link.
