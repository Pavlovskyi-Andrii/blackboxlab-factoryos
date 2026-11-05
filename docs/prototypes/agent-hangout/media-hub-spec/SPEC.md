# MyCast + AI Hangout media hub: architecture and screen spec · Issue #221

**Status: DESIGN SPEC ONLY. Nothing is implemented, and nothing may be built until both gates are open:**
1. the owner approves the #220 video result as visually good;
2. the owner picks one visual direction among #216, #217 and #218.

Until then this file is the deliverable. It contains an architecture review, screen wireframes and fields, API contracts, and the acceptance checklist.

## 1. Principles
- **No second queue.** Podcast and video orders are Relay tickets (`relay_execution.py`). They use the existing states and run-id fences, and they appear in Worker Center and Telegram like every other ticket.
- **No second media store.** Playable files use the existing durable media archive and its signed URLs (`/media-archive/{id}?token=…`). The MyCast delivery log stays the single record of "sent to Telegram".
- **Owner-only first.** Every route below requires the owner session. Viewer or customer access comes later and needs separate authorisation.
- **Facts only.**
  - "Live" appears only when a real run with a current heartbeat is attached.
  - "Delivered" appears only when there is a delivery record.
  - "Published" appears only when a publisher receipt exists, and publishing itself stays behind the existing approval gate.
  - Demo content always carries a DEMO chip.
- **One place per thing.**
  - Customer-facing MyCast stays separate from internal FactoryOS control.
  - The Globe/topic picker from #107 (ChatGPT) is reused, not redrawn.
  - Voice settings stay with #140/#141.

## 2. Architecture
```
Owner (web, Android first)
  └─ Media hub UI (static/index.html section "Media", EN/UK/RU)
       ├─ Hangout   → read-only view of one experiment room (Relay ticket thread + evidence notes)
       ├─ Watch     → library items with status=approved, played from signed media URLs
       ├─ Order     → POST order → creates a Relay ticket (kind=media_order) → worker claims → artifacts
       ├─ Requests  → Relay tickets filtered by kind=media_order, lifecycle from Relay events
       └─ Library   → media items (scripts, briefs, MP3/MP4, transcripts), versioned file refs
Server (app.py, new module media_hub.py)
  ├─ media_items table (SQLite, DATA_DIR) — metadata only, files stay in the media archive
  ├─ uses: RelayQueue (create/claim/events), media archive signer, MyCast DeliveryLog, provider registry (real connected providers only)
  └─ no new worker type: the existing Claude worker (and later Gemini/ChatGPT lanes) claims media_order tickets
```

## 3. Screens (Android first; desktop widens to two columns)

### 3.1 AI Hangout
```
┌──────────────────────────────┐
│ [DEMO] or [LIVE · run r-…]   │  ← LIVE only with a real run_id + fresh heartbeat
│  ◐ Mind A  ───────  ◑ Mind B │  cinematic hero from the chosen visual (#216/#217/#218)
│  Mission: «…»                │
├──────────────────────────────┤
│ Participants: Claude · Builder│  role chips; provider names only if really connected
│ Timeline ▾                   │  timestamped messages / evidence / decisions
│  05:41 claim  T-…            │
│  05:43 evidence E-3 (link)   │
│ Costs: $0.00 · 12/24 turns   │  from run telemetry, else "—"
└──────────────────────────────┘
```
**Fields:** `ticket_id`, `mission`, `participants[{agent, role, connected:bool}]`, `events[{ts, kind, text, ref}]`, `cost_usd`, `turns_used/turns_max`, `mode: demo|live`.

### 3.2 Watch
```
┌──────────────────────────────┐
│ [poster]  ▶  0:17            │  <video controls playsinline> from a signed URL
│ AI Hangout · Scene B         │
│ 5 Nov 2026 · UK · private    │  privacy: private | unlisted | public (public only with publish receipt)
│ Script: Claude · Visual: code│  provenance
│ Voice: Piper uk_UA · captions│
│ Sources (3) ▸                │
└──────────────────────────────┘
```
**Fields:** `id`, `title`, `kind: audio|video`, `duration_s`, `poster_url`, `media_url (signed, expires)`, `released_at`, `language`, `provenance{script_by, visual_by, voice_model, render_tool}`, `captions_url?`, `sources[{title,url,date}]`, `privacy`, `progress_s` (per viewer, local only).

### 3.3 Order a podcast
```
┌──────────────────────────────┐
│ Who writes it  [Claude ▾]    │  only providers with a working connection
│ Topics  (Globe picker #107)  │
│ YouTube sources (0/10) [+]   │
│ Language  UK · RU · EN       │
│ Format    Audio · Video      │
│ Length    5 · 10 · 15 min    │
│ Voices    [Charon/Kore ▾]    │  from #140 voice settings
│ Deliver   Telegram 06:00 ▾   │
│ Exclude   [sources, topics]  │
├──────────────────────────────┤
│ Estimate: ~4 TTS calls,      │  computed before submit; $0 on free tier, otherwise blocked
│ free tier · $0               │
│ [Create request]             │  creates a Relay ticket; nothing external happens yet
└──────────────────────────────┘
```
There are no payment buttons. If any part of an order would need a paid call, submit is disabled and the form says which part.

### 3.4 Requests (lifecycle)
`draft → submitted → queued → claimed → generating → review → delivered | failed | blocked`

| Hub state | Relay source |
|---|---|
| draft | local form, not yet sent |
| submitted / queued | ticket created, `status=queued` |
| claimed | `claimed` event with `run_id` |
| generating | `running` / `checkpoint` events |
| review | artifact attached, waiting for owner approval |
| delivered | MyCast delivery log entry or owner-approved library item |
| failed / blocked | Relay `failed` / `blocked`, with the worker's reason |

Each row shows the ticket ID with a link, the run ID, cost, source checks and the last event time. A stale claim shows **stale**, never "generating".

### 3.5 Library
Shows scripts, source briefs, MP3/MP4, transcripts and their versions. Every item is either private or public, stated explicitly. Files are stored as versioned file references in the media archive, never as base64 in Notion or the repo.

### 3.6 Navigation
The left nav gains one section, **Media**, with five entries: Hangout, Watch, Order, Requests, Library. It also cross-links to Agent Office, Content Factory, MVP Factory and MyCast, and adds no new queue screen. It follows T-594's nav map and the locale-parity tests.

## 4. API contracts (all owner-session only; JSON)
```
GET  /api/factory/hub/items?kind=&status=&limit=50
  → {items:[{id,title,kind,duration_s,poster_url,released_at,language,privacy,status,provenance,sources[]}], next}
GET  /api/factory/hub/items/{id}
  → item + media_url (signed, ≤1 h) + captions_url? + versions[{v, created_at, ref}]
POST /api/factory/hub/items/{id}/approve      body {privacy:"private"|"unlisted"}
  → {status:"approved"}   (public requires the existing publish approval flow, never this route)

POST /api/factory/hub/orders
  body {provider, topics[], youtube_sources[≤10], language:"uk"|"ru"|"en", format:"audio"|"video",
        minutes:5|10|15, voices{a,b}, delivery{channel:"telegram", local_time:"06:00"}, exclusions[]}
  → 201 {ticket_id, estimate{tts_calls, cost_usd, free_tier:true}}  |  409 {reason:"paid_call_required"|"provider_not_connected"}
GET  /api/factory/hub/orders?limit=50
  → {orders:[{ticket_id, hub_state, run_id?, cost_usd, last_event_at, artifacts[], blocker?}]}

GET  /api/factory/hub/hangout/{ticket_id}
  → {mode:"demo"|"live", mission, participants[], events[], cost_usd, turns{used,max}}
```
**Input rules:**
- YouTube URLs must be `https://` on youtube.com or youtu.be. Text fields are length-capped, and server-side HTML is escaped.
- Responses never include tokens, emails or chat IDs.

## 5. Acceptance checklist (for the implementation issues created after approval)
- [ ] Gates recorded: #220 video approved and visual (#216/#217/#218) selected, with links.
- [ ] Every route returns 401 without the owner session, with a test per route.
- [ ] An order creates exactly one Relay ticket. Replaying the same request (idempotency key) creates none.
- [ ] The lifecycle mapping matches §3.4, with tests for stale claim, blocked, failed and delivered.
- [ ] "Live" appears only with a fresh heartbeat and a run ID. "Published" appears only with a publish receipt. Demo items always show DEMO.
- [ ] Media plays through signed URLs that expire. A tampered token gets 403.
- [ ] Submit is disabled when an order would need a paid call, and the form explains why.
- [ ] EN/UK/RU parity (`test_locale_parity.py`), navigation (`test_navigation.py`), no horizontal overflow at 390 px, keyboard and screen-reader labels.
- [ ] External URLs and HTML are sanitised, and no secrets appear in responses or logs.
- [ ] No change to #107, #140 or #141 files. The Globe picker is imported, not copied.

## 6. Decomposition after approval (non-overlapping file scopes)
| Issue | Scope | Files |
|---|---|---|
| H1 | media_items store + read APIs + signed playback | `media_hub.py`, `test_media_hub.py`, route wiring in `app.py` |
| H2 | orders → Relay tickets + lifecycle mapping | `media_hub.py` (orders section), `test_media_hub_orders.py` |
| H3 | Watch + Library UI | `static/index.html` (Media section only) |
| H4 | Order + Requests UI (imports #107 picker) | `static/index.html` (Order/Requests panels) |
| H5 | Hangout view from the chosen visual | `static/index.html` (Hangout panel), assets from the winning concept |

Before starting, each issue checks `AGENTS.md`, `ROADMAP.md`, `Owner:`/`Depends:` and open PRs, per the coordination rules.
