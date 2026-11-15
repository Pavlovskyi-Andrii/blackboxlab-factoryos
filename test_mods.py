"""T-611 Mods & skills: vendored plugins (A).

Run: python test_mods.py
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODS = ROOT / "mods"


def require(ok, msg):
    if not ok:
        raise AssertionError(msg)


def test_vendored_plugins():
    readme = (MODS / "README.md").read_text(encoding="utf-8")
    for folder, skill in (("pstack", "poteto-mode"), ("grilling", "grilling"), ("product-film", "product-film")):
        manifest = json.loads((MODS / folder / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        require(manifest["name"] == folder, f"{folder}: plugin name {manifest['name']!r}")
        require(manifest.get("license") == "MIT", f"{folder}: license not recorded")
        require((MODS / folder / "LICENSE").is_file(), f"{folder}: upstream LICENSE missing")
        text = (MODS / folder / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
        require(re.search(rf"^name: {re.escape(skill)}$", text, re.M), f"{folder}: SKILL.md lost its name")
        require(f"`{folder}/`" in readme, f"{folder}: provenance row missing in mods/README.md")
    require(re.search(r"\| `[0-9a-f]{7}` \(", readme), "upstream commits not pinned in mods/README.md")


def test_no_binaries_or_external_publishing():
    for path in MODS.rglob("*"):
        if not path.is_file():
            continue
        head = path.read_bytes()[:4]
        require(head not in (b"\x7fELF", b"MZ\x90\x00") and head[:2] != b"MZ" and head not in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe"),
                f"executable binary vendored: {path.relative_to(ROOT)}")
    pf = MODS / "product-film" / "skills" / "product-film"
    require(not (pf / "bin").exists(), "product-film bundled binaries must stay removed")
    require(not (pf / "scripts" / "publish.sh").exists() and not (pf / "scripts" / "_common.sh").exists(),
            "display.dev publish scripts must stay removed")
    skill = (pf / "SKILL.md").read_text(encoding="utf-8")
    front = skill.split("---", 2)[1]
    require("publish.sh" not in front and "dsp " not in front, "publish tools must not be pre-allowed")
    require("FactoryOS build" in skill and "Never publish" in skill, "product-film FactoryOS banner missing")
    require("display.dev" not in (pf / "references" / "publish.md").read_text(encoding="utf-8").split("FactoryOS removed")[1],
            "publish reference must keep review files local")


def test_pstack_bundle_is_complete():
    skills = MODS / "pstack" / "skills"
    poteto = (skills / "poteto-mode" / "SKILL.md").read_text(encoding="utf-8")
    # poteto-mode routes to bundled skills by name; each one it names must ship with it.
    for name in ("architect", "swarm", "arena", "interrogate", "unslop", "technical-writing", "no-comments",
                 "figure-it-out", "show-me-your-work", "benchmark-checklist"):
        require(f"**{name}**" in poteto or f"`/{name}`" in poteto, f"poteto-mode no longer routes to {name}")
        require((skills / name / "SKILL.md").is_file(), f"pstack skill {name} missing")
    for ref in re.findall(r"\(`(playbooks/[a-z0-9-]+\.md)`\)", poteto):
        require((skills / "poteto-mode" / ref).is_file(), f"poteto-mode playbook {ref} missing")
    require((MODS / "pstack" / "docs" / "harness" / "claude-code.md").is_file(), "Claude Code adapter missing")
    require((MODS / "pstack" / "agents" / "poteto-agent.md").is_file(), "poteto-agent subagent missing")


TESTS = [test_vendored_plugins, test_no_binaries_or_external_publishing, test_pstack_bundle_is_complete]

if __name__ == "__main__":
    for t in TESTS:
        t()
        print("ok", t.__name__)
    print(f"Mods tests passed: {len(TESTS)}")
