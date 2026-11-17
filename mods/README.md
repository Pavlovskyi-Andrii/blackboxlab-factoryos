# FactoryOS mods (vendored Claude Code plugins)

Each folder here is a Claude Code plugin (`.claude-plugin/plugin.json` + `skills/`). Nothing here loads by itself:
the owner switches a mod on in the dashboard (sidebar → **Mods & skills**), and the Claude worker then starts
`claude` with `--plugin-dir mods/<folder>` for that run only. Switched off, the folder is just files.

| Mod | Folder | Upstream | Commit | License | Removed or changed in FactoryOS |
|---|---|---|---|---|---|
| poteto-mode (pstack 0.15.42) | `pstack/` | `cursor/plugins` → `harness/pstack/claude-code` | `bf0c7cd` (2026-11-14) | MIT, Lauren Tan | `docs/guide/` (2.4 MB of guide pages and images) and `skills/statechart/scripts/test/` (TLA+ test corpus) dropped. Code unchanged. |
| grilling | `grilling/` | `mattpocock/skills` → `skills/productivity/grilling` | `5863806` (2026-11-12) | MIT, Matt Pocock | `plugin.json` added. Skill text unchanged. |
| product-film 0.2.0 | `product-film/` | `display-dev/product-film` → `product-film/` | `1a099f3` (2026-10-05) | MIT, display.dev | Bundled prebuilt `jq` binaries (`bin/`), `scripts/publish.sh` and `scripts/_common.sh` (upload to display.dev) removed; publish tools dropped from `allowed-tools`; `SKILL.md` gets a FactoryOS banner (no publishing, no paid calls, BLOCKED when Node/ffmpeg/Playwright are missing); `references/publish.md` rewritten to keep review files local. |

Rules that always win over a mod's own text: the repository `CLAUDE.md` (no push to main, no deploys, no paid calls,
no publishing without the owner's approval, no secrets). pstack's "external actions proceed without asking" and
grilling's "wait for the user's answers" are both overridden for the headless worker by the system prompt it adds
(`autopilot/mods_runtime.py`).

Updating a mod: re-copy from the upstream commit, re-apply the changes in the table, update the commit column, and
run `python test_mods.py`.
