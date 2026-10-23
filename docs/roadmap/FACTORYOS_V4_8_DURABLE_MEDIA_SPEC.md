# FactoryOS v4.8 — Durable Finished Media

**Status:** DONE — CI, production deploy and live post-redeploy persistence verification passed on 2026-10-23.  
**Goal:** prevent finished Media Finisher videos from disappearing when the Render worker redeploys or restarts.

## Problem found in production

The Media Finisher service currently serves generated files from its local `/files/...` filesystem. That worker has no persistent disk. After a deploy/restart, previously generated master/short URLs can return **404**, even though FactoryOS still has their artifact records.

That is unacceptable for Approval → Publishing because a queue item can otherwise point at a video that no longer exists.

## v4.8 flow

```text
Media Finisher READY
→ detect worker-local /files URL
→ stream finished deliverable to FactoryOS persistent disk
→ calculate SHA-256 + bytes
→ replace artifact URL with signed FactoryOS /media-archive URL
→ update edit-job master/short URLs
→ HUMAN APPROVAL unlocks
→ immutable publish snapshot
→ schedule
→ publisher
```

## Durable archive

FactoryOS already has a persistent Render disk mounted under its `DATA_DIR`. v4.8 adds a separate `media_archive` directory there.

For worker-local finished media:
- copy is streamed in 1 MB chunks; the whole video is never loaded into application memory;
- an individual archive size ceiling is enforced;
- SHA-256, byte count, original source URL, edit-job ID and artifact ID are persisted;
- the public delivery URL is signed with the existing FactoryOS secret;
- final master and Shorts/Reels artifact URLs are rewritten to the durable URL;
- matching URLs in the persisted edit report are rewritten too.

External media URLs that are already durable are left untouched.

## Approval boundary

When the selected Media Finisher deliverable still points to an ephemeral worker URL, Approval Studio is **not ready**.

Approval unlocks only when:
1. the edit job is READY;
2. current package/variant provenance is valid;
3. the exact publishable artifact exists;
4. worker-local media has been copied to durable FactoryOS storage.

Archive failure is visible and cannot silently fall through to publishing.

## Configuration

- `FACTORY_MEDIA_ARCHIVE_MAX_BYTES` — max bytes per archived deliverable (default 600 MB).
- `FACTORY_MEDIA_FINISHER_EPHEMERAL_HOSTS` — comma-separated worker hosts whose `/files/` URLs must be archived.
- `FACTORY_PUBLIC_BASE_URL` — FactoryOS public base URL used to build signed durable media links.

## Acceptance

- [x] worker-local `/files/` URLs are classified as ephemeral;
- [x] archive copy is streamed to persistent FactoryOS storage;
- [x] SHA-256 + source provenance are persisted;
- [x] edit artifact/report URLs are rewritten to the durable URL;
- [x] approval is blocked while ephemeral media is not archived;
- [x] approval unlocks after durable copy succeeds;
- [x] signed `/media-archive/{id}` route added;
- [x] zero-spend regression coverage added;
- [x] GitHub CI PASS — run `39933231662` on commit `d85db541aacebbbefbc2035ad871316aee4355ec`;
- [x] FactoryOS production deploy LIVE — `dep-dbdim1k9v7es73e0ulh0`;
- [x] real archived Media Finisher outputs survive redeploy: startup inventory after deploy verified **5/5 present, 0 missing, 261,314,094 bytes** on persistent storage; existing approval/publishing regressions protect the durable-media gate.


## Live closure evidence — 2026-10-23

FactoryOS startup verification `DURABLE_MEDIA_INVENTORY` ran after a fresh production deploy and reported `status=ready`, `checked=5`, `present=5`, `missing=0`, `bytes=261314094`. This closes the persistence/redeploy acceptance requirement without relying on the ephemeral Media Finisher filesystem.
