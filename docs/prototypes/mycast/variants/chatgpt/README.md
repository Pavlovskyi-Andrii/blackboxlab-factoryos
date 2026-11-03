# MyCast — ChatGPT independent variant (production prep, not an audio demo)

**Issue #124** · **Status:** SCRIPT / BLOCKED on a verified zero-extra-spend *Ukrainian* TTS path; no playable audio in this PR. The requested acceptance is an **actual 90–120-second two-voice recording**. A script does not satisfy that acceptance. This alternative will not be confused with Claude’s existing Piper/Gemini pilot or Gemini’s planned variant.

## Source brief, 3 November 2026 (shared, nonprivate project facts)

For a fair A/B/C comparison, the agents should receive exactly this fact brief and a target 90–120 s format; final voice/mix choices remain independent:

- [FactoryOS MyCast pilot and zero-spend TTS workflow — PR #110](https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/pull/110): prototype and documented delivery workflow (merged, 2 Nov).
- [Daily MyCast script/render/Telegram delivery — PR #117](https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/pull/117): implementation merged 2 Nov. Merge is not proof each future morning was delivered.
- [Gemini two-host voices with Piper fallback — PR #127](https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/pull/127): server-side code merged 2 Nov, but free model availability and production voice quality are separate questions.
- [Claude↔ChatGPT handoff protocol — PR #128](https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/pull/128): spec merged 3 Nov, does not prove a live conversation bridge.

Only internal engineering news, not global news. These references are auditable, but the owner must approve the shared brief before comparing with Claude’s **different** already-rendered episode.

## Original Ukrainian dialogue draft

**Host A — теплий, спокійний голос; Host B — жвавий, розмовний голос.**

**A:** Вітаю! Це MyCast — короткий аудіобрифінг про те, над чим сьогодні працює наша цифрова команда. І цього разу в нас не просто список задач, а історія про те, як ідея стає справжнім продуктом.

**B:** Почнімо з головного. У FactoryOS уже є пілот персонального подкасту. Код для сценарію, створення аудіо та надсилання в Telegram потрапив до основної гілки проєкту другого листопада.

**A:** Але тут важлива деталь: коли зміни в GitHub об’єднані, це ще не означає, що кожен наступний випуск гарантовано доставлено. Для цього потрібні записи фактичних відправлень, перевірка голосу і зворотний зв’язок слухача.

**B:** Саме якість голосу стає окремим експериментом. Команда додала варіант із двома голосами Gemini та запасний сценарій на Piper. І ми не називаємо це перемогою, доки не прослухаємо результат.

**A:** Є ще одна важлива частина. Claude та ChatGPT погодили правила передачі задач: у кожної роботи має бути власник, а статус «призначено» не можна плутати зі статусом «виконується».

**B:** Тобто чесний прогрес — це не красива зелена крапка, а підтверджений запуск, коміт, перевірка та результат. Саме такий принцип наша команда хоче бачити і в Telegram, і на сайті.

**A:** А для MyCast мета ще простіша: за кілька хвилин дати людині корисну, перевірену історію, яку приємно слухати.

**B:** На цьому все. У наступному експерименті порівняємо різні сценарії, голоси й темп — і виберемо не найгучнішу модель, а той випуск, який справді хочеться дослухати.

**A:** Дякуємо, що були з нами. До наступного ранку!

*Draft is original; no third-party copyrighted audio or music used.* Approximate speaking time depends on language-specific TTS speed. The producer must measure final duration after rendering; target 90–120 seconds, edit script to fit.

## Technical constraints and production plan

1. **No paid voice calls.** We checked the current execution environment: `espeak` and `ffmpeg` are available, but there is **no Ukrainian `uk` voice** in its listed voice inventory. A Russian phonetic approximation is not an acceptable quality baseline for Ukrainian; do not silently label it as natural Ukrainian TTS. Cloud `gTTS` would require network access, consent to send text, and an eligibility/terms check. A Gemini key in someone else's runtime is not authorization for a paid call.
2. Find a legally available, offline Ukrainian TTS voice installed on an **already approved** host or a confirmed free-tier voice engine with owner approval. Record engine, model/voice, release and licence; avoid another paid server/API.
3. Render A and B independently, normalize peak and loudness with `ffmpeg`, use pauses and original optional intro sting only if rights allow. Create and keep the **actual** 90–120-second playable MP3 plus generated transcript in `docs/prototypes/mycast/variants/chatgpt/`.
4. Run duration/sanity/rights checks and give the owner the playable file for listening. Compare factuality, source links, clarity, pronunciation, speaker contrast, mix, reproducibility and real costs to other variants. Do not send to Telegram or publish without explicit approval.

## Verification ledger

| Acceptance condition | Status |
|---|---|
| Original Ukrainian two-host script and source links | Drafted |
| Independent isolated files and one PR | Done for script, not rendered artifact |
| Proven zero-extra-spend Ukrainian voices | **Blocked** |
| Actual playable 90–120 s MP3 | **Not produced** |
| Voice licence and model provenance | **Not verified** |
| Owner listening comparison | **Not started** |

**Next action is gated:** select/verify a Ukrainian TTS path that does not incur new charges; only then render an honest audio artifact.