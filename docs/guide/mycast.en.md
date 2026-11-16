# MyCast: owner's guide

MyCast is a personal podcast service that automatically gathers current material, writes a dialogue between two hosts and sends the audio episode straight to the owner's Telegram.

> The guide is based on a draft by Gemini (PR #265, task #206); facts were checked against the code and extended by Claude on 2026-11-08.

---

## 1. When the episode arrives

- **When**: the goal is an episode in Telegram before 06:00 Kyiv time. The first attempt starts at 05:10 (nothing runs earlier), with up to 3 attempts per day (`autopilot/mycast_daily.py`).
- **How**: the EC2 worker asks Claude to write a script (a web search for fresh news from the last 48 hours) and saves it to the `mycast/daily` branch. The FactoryOS server (Render) then voices it with Gemini voices and sends it to the owner's linked Telegram chat. The bot token and the Gemini key stay on the server.
- **Episode text**: after the audio, the full text with sources arrives. If the audio could not be produced at all, the text arrives as a fallback so the episode can still be read.
- **Language**: the owner's daily episode is currently always in Ukrainian (`language="uk"`).
- **Format**: an MP3 audio file with an artist tag (`MyCast`), the episode title and a description with the estimated playback length.
- **Deduplication**: every episode has a unique identifier (`mycast-...`). The server keeps a record of successfully delivered episodes and prevents duplicates from being sent again.

---

## 2. Voices and speech synthesis

### Main mode: Gemini TTS
- The dialogue is voiced through the Google Gemini API (`gemini-2.5-flash-preview-tts` or a similar available speech model).
- **Two hosts**: lines are split between host A and host B. By default these are `Charon` and `Kore`.
- **Voice choice (#140)**: the owner can pick the pair via `GET/POST /api/factory/voice/settings` (owner only). The rule: host A is a male voice, host B a female voice, and the two voices differ; gender is judged by ear, not officially. Daily delivery reads the saved pair on every run; if nothing is saved it uses `FACTORY_MYCAST_VOICE_A/B`, otherwise `Charon` + `Kore`.
- **Generation in parts**: the text is split into chunks (~2800 characters, about 2 minutes of speech each), which keeps it within the Gemini free tier's requests-per-minute (RPM) limits.

### Fallback mode: Piper TTS
- If Gemini voices are unavailable (no key, quota exhausted, an error), the worker switches to **Piper**.
- Piper renders the episode in **GitHub Actions** (the `mycast-render.yml` workflow, at no cost); the worker downloads the finished MP3 and hands it to the server for sending. This is not local synthesis on EC2.

### Audio quality control (Audio QC)
Before it is sent to Telegram, the audio goes through automatic validation:
- **Recording length**: the actual duration is compared with the duration expected from the word count (a pace of ~140 words per minute, with an allowed deviation from 0.45x to 2.2x).
- **No silence**: pauses and silence (RMS < 160) longer than 6 seconds in a row are not allowed.
- **Chunk integrity**: every speech chunk is checked for truncation (ratio of duration to amount of text).
- **MP3 format**: the file must contain at least 20 valid MPEG frames and at least 90% decodable data.

If the check fails, the episode is rejected, the lock is released, and the system moves to the fallback path or a retry.

---

## 3. What to do if the episode did not arrive

If the expected episode did not show up in Telegram on time:

### Step 1. Check the Telegram bot pairing
- Make sure the bot is activated and the owner's chat is paired with the server (status paired). If the bot is not paired, the server returns the error `409 Telegram owner chat is not paired`.

### Step 2. Check the Gemini API key
- The server (a Render environment variable) must have the `FACTORY_GEMINI_API_KEY` key set (Google AI Studio). The key is never put in the repository.
- If the key is missing (`409 gemini key not configured`), wrong (`invalid_key`), or the model is unavailable (`model_not_found`), the main Gemini voice cannot run.

### Step 3. Check the Gemini rate limits
- The free tier has a limit on requests per minute (RPM). On HTTP 429 the server makes up to 2 retries: the first pause is 30 seconds, the second 60 seconds. There is no paid model in reserve. If the quota stays exceeded for long, the worker switches to Piper.

### Step 4. Check for Audio QC errors
- If the synthesizer produced an empty file, a truncated piece, or audio with long silence, the `AudioQCError` guard triggers. The recording is not sent, so the chat is not spammed with broken audio.

### Step 5. Check the EC2 worker status
- Make sure the worker instance started successfully on schedule and has network access to the factory server.
- If sending fails, the server automatically releases the episode ID in `DeliveryLog` (`release`), so rerunning the job on the worker can deliver the podcast again.

---

## 4. Public MyCast page for listeners (`/mycast`)

Separately from the owner's daily episode, there is an open beta for listeners:

- **Configurator**: topics (search suggests narrow subtopics, for example «Growth hacking: ідеї для стартапів» (Growth hacking: ideas for startups)), region, social networks, voice, schedule. Until the listener signs in, everything is stored in their browser.
- **Voice samples**: 30 Gemini voices with real samples. Up to 40 new samples per day (`MYCAST_VOICE_SAMPLE_DAILY_CAP`); cached ones always play.
- **Gemini demo**: about 15 seconds; up to 30 new demos per day across everyone (`MYCAST_DEMO_DAILY_CAP`) and up to 5 per visitor. Without a key or after the limit, the page openly falls back to the browser's voice.
- **Sign-in**: via Telegram or Google. Only the name, sign-in method, settings and (for Telegram) the chat are stored. Deleting everything takes one button.
- **Mailing (step 07)**: profile approval, connecting Telegram and signing in **never** turn the mailing on. It needs an approved profile, a test message to your own chat and the consent checkbox, then a separate button «Увімкнути розсилку» (Turn on mailing). «Зупинити розсилку» (Stop mailing) really turns it off. Changing the profile after approval pauses the mailing. Messages go only to the listener's own chat, no more than 3 per day.
- **Honest limitation**: regular personal episodes for listeners are not generated yet; the mailing stores consent and the schedule.
- **Invitations**: 7 free days at the start and +7 for every invited friend (the friend starts with 14 days). This is an open beta: the days will start counting once regular episodes launch, and there is no payment.
