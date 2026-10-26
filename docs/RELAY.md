# FactoryOS Relay

Relay is the mobile inbox/task layer for FactoryOS.

## Telegram

After the existing FactoryOS Telegram pairing is complete:

- any ordinary text, link, voice note, video, document or photo becomes a persistent Relay ticket;
- /tasks or /relay shows active tickets;
- /new <text> creates an explicit ticket;
- /work R-0001, /need R-0001, /done R-0001 and /inbox R-0001 change ticket state;
- every new ticket includes inline buttons for In progress, Need you, Done and Inbox;
- ordinary text still passes through to the legacy agent bridge, so Relay adds durable task history without breaking processing.

Telegram update retries are deduplicated by update id.

## Mobile board

Open /relay on the FactoryOS host while signed in. The board has:

- Inbox
- In progress
- Need you
- Done

It refreshes automatically and supports creating and moving tickets.

## Data

Tickets live in DATA_DIR/relay.json on the existing FactoryOS persistent disk. Each ticket keeps source metadata, notes and immutable history events. Telegram file ids are stored for attachments so voice/video/document inputs are not lost even before transcription or analysis is added.

## Operator boundary

Relay tickets include an Operator state placeholder. Browser/app execution will be layered on top of tickets. Any purchase/payment action must require explicit owner confirmation before the final external action.
