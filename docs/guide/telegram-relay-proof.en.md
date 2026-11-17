# Telegram, Relay and the /proof command

How a task from Telegram becomes a Relay ticket, how the owner answers and accepts the result, and how `/proof` checks the whole chain from server facts.

## What it is

- **Relay** is the FactoryOS task log. Every task is a ticket with a number like `R-0001` and an append-only history of events.
- **The Telegram bot** is the owner's remote control. It works only in one paired private chat; messages from other chats are ignored.
- Pairing is done once with `/pair CODE` (FactoryOS shows the code; it is valid for 10 minutes).

## How a task reaches Relay and comes back to Telegram

1. Ordinary text, a link, a voice note, video, document or photo in the paired chat creates a ticket. The default executor is Claude.
2. `/new text` creates a ticket with no executor; the bot offers the buttons "🟠 Claude" and "🔵 Gemini (через GitHub)".
3. A repeated delivery of the same Telegram message does not create a second ticket (checked by `update_id`).
4. When the worker reports a stage (took the task, working, commit, push, done, needs help, error), the server sends a stage card to the chat.
5. If Telegram accepted that message, the server writes an `owner_notified` event into the ticket. This is the delivery receipt that `/proof` reads later.

## How the owner answers and accepts

- Ticket buttons (the bot labels them in Russian): "▶️ В работу" (start), "🙋 Нужно от меня" (needs me), "✅ Готово" (done), "↩️ Inbox", "↻ Retry", "✖ Cancel queued", "🔄 Обновить" (refresh).
- If the worker says it needs help, answer with what is needed or press "↻ Retry".
- While a task is running, "✅ Готово" is refused: wait for the result first.
- If the result has a PR, the task closes by itself after CI and the merge, and the buttons "✅ Принял" (accepted) / "👎 Не то" (not it) arrive. "👎 Не то" sends the ticket back to need_you.
- If there is no PR, you can close it by hand with a reason: `/done R-0001 reason`.

## What /proof does

Send `/proof R-0001`. The bot replies with an acceptance report for that one ticket. The report is built only from the ticket's history on the server; the bot asks no model and calls neither Telegram, GitHub nor Render.

| Stage | Where the fact comes from |
|---|---|
| message from the paired chat | the ticket source: channel, chat id, update id |
| exactly one ticket | no other ticket for the same message |
| worker claim (run_id) | a `claimed` event with a worker id and a `run_id` |
| running | a `running` event with the same `run_id` |
| done | the final event of the same `run_id`, in the right time order |
| worker result | the text summary in the `done` event |
| notice delivered to Telegram | an `owner_notified` receipt, at most one hour after the final event |

- Verdict: "✅ VERIFIED by the server" only when all 7 stages are present and there are no problems. Otherwise "❔ NOT verified" plus the list of problems.
- The "Code" block shows the commit and branch (as the worker reported them) and the PR link. PR, CI, merge and deploy stay "not verified" until the server has recorded them.
- Times are in UTC, secrets are removed. The owner gets the same report from `GET /api/relay/{id}/acceptance`.

## Why "assigned" is not "running"

- Assigning only puts the ticket in the queue: the bot's card says `Назначено (запуск не подтверждён)` (assigned, start not confirmed).
- "Running" begins only when a worker has taken the task itself and the server recorded `claimed` with a `run_id`, and then `running`.
- If the worker sends no heartbeat for too long, the task shows as "⚠️ Worker без связи" (stale), not as running.
- Gemini has no Relay runner: a ticket assigned to Gemini will not start by itself. Gemini works through GitHub issues labelled `gemini`.

## Where to look

- In Telegram: `/tasks`, `/task R-0001`, `/history`, `/proof R-0001`.
- On the site: the `/relay` board (Inbox, In progress, Need you, Done) once the owner is signed in.

## Limits

- The live owner acceptance has not been done yet: it is task T-591-H, and its status is shown in "Your tasks".
- `/proof` does not check PR, CI, merge or deploy itself: it only shows whether those facts were recorded.
