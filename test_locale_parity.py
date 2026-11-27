"""T-534 EN/UK/RU localization parity regression.

Static checks always run: EN is the canonical dashboard key set. UK and RU must have exactly the
same keys (I18N literal + the Object.assign extensions) and the same {placeholders}. Every key the
markup or script references statically must exist. UK/RU values may equal EN only for allowlisted
product names and glossary terms. UK copy must not contain RU-only letters and RU copy must not
contain UK-only letters. Strings that used to be hardcoded in English must not come back as
literals. The checker is also run against deliberately broken tables, so we know it actually
catches a missing key.

The fixture check evaluates the real I18N tables, TASK_COPY, taskCopy() and tr() under Node. It
renders a representative EN/UK/RU dashboard fixture (the static shell, every statically referenced
key and every roadmap task card) and asserts no raw keys, unresolved placeholders or known EN
fallback strings appear in UK/RU. Node is required when FACTORYOS_REQUIRE_NODE=1 (CI); without it
the check is reported as SKIPPED, never as passed.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HTML = Path(__file__).resolve().parent / "static" / "index.html"
LOCALES = ("en", "uk", "ru")
PAIR = re.compile(r'"((?:[^"\\]|\\.)+)":"((?:[^"\\]|\\.)*)"')
PLACEHOLDER = re.compile(r"\{(\w+)\}")
FOREIGN_LETTERS = {"uk": re.compile(r"[ыэъёЫЭЪЁ]"), "ru": re.compile(r"[іїєґІЇЄҐ]")}

# UK/RU may keep the EN value only for product/workspace names and glossary/technical terms.
SAME_AS_EN = {
    # product / workspace names
    "approval.title", "brain.nav", "cycle.title", "discovery.nav", "experiment.title", "finisher.nav",
    "finisher.title", "intel.title", "owner.builder", "package.title", "performance.title",
    "publishing.title", "revideo.nav", "variant.title", "navGroup.mvp", "nav.linkedin", "nav.olx",
    "mvpb.crm",  # T-742: the product name «Faceless Models CRM», the same on the dashboard and the full MVP page
    # product role/phase names (owner 2026-11-11)
    "mvpc.phase.battle", "mvpc.phase.build", "mvpc.phase.promote", "mvpc.phase.learn", "mvpc.engine.content_factory",
    # glossary / technical terms
    "approval.hook", "build.workflow", "dc.cpu", "dc.doneCriteria", "dc.state.human", "dc.tl.push",
    "discovery.short", "finisher.routeQa", "package.cta", "qa.roadmap", "stage.qa",
    # T-MODS mod names are product names (owner 2026-11-15)
    "mods.m.poteto-mode.name", "mods.m.grilling.name", "mods.m.product-film.name", "mods.m.revideo.name",
    "mods.m.media-finisher.name", "mods.m.explainer-motion.name",
    # T-MODS-D duel: symbols, arm letters and the Relay product name only
    "duel.noScore", "duel.result", "duel.ticket",
}

# English UI strings that used to be hardcoded outside tr(). They must stay localized.
KNOWN_FALLBACKS = [
    "Restart Factory", "Checking…", "Loading history…", "Could not load team", "Could not load job outputs",
    "Could not load agent history", "Viewer link copied", "MCP name and endpoint are required",
    "MCP configuration added", "Could not add MCP: ", "MCP enabled", "MCP disabled", "Could not update MCP",
    "MCP removed", "Could not remove MCP", "Write a memory first", "Memory saved", "Could not save memory",
    "Memory archived", "Could not archive memory", "Improvement dismissed", "Add a title", "Job created",
    "Published state confirmed", "Add at least one real metric", "Metrics synced", "Invalid JSON",
    "Proposal created", "Selected job assigned to ", "Experiment evaluated: ", "no decision",
    "Treatment rolled out", "Workflow rolled back", "Experiment rejected", "Human Approval", "Publishing",
    "Cut / captions / graphics", "Short clips", "Approved publish snapshot", "Approved media", "Hypothesis",
    "Measured comparison", "Control → treatment", " assigned", " partial reruns", "Agent",
    "Platform target", "Real platform post ID", "Post URL (optional)", "Views (blank = unavailable)",
    "Retention % (blank = unavailable)", "Likes (blank = unavailable)", "Proposal title",
    "Why should FactoryOS test this change?", "Reject reason", "Not enough value / keep control",
    "Rollback the active treatment to the pre-rollout workflow?",
]
# Lowercase-only EN words that UK/RU used to show untranslated; they must not render in UK/RU.
KNOWN_EN_LEFTOVERS = [
    "Description", "Hashtags", "Thumbnail concept", "Publishing metadata", "Fact-check report", "Voice-over",
    "Media brief", "Media adapters", "Breakout score", "Engagement rate", "Originality guard", "Media provider",
    "Partial rerun", "Structured QA", "Provenance", "Evidence", "edit jobs", "worker runs", "Close",
    "Allowed tools (comma-separated)", "Discover tools", "Available tools", "Design Partner",
]


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def extract(html):
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]
    i18n = script[script.index("const I18N="):script.index("const TASK_COPY=")]
    task_copy = script[script.index("const TASK_COPY="):script.index("function taskCopy(")]
    task_fn = re.search(r"^function taskCopy\(t\)\{.*\}$", script, re.M).group(0)
    assigns = [l for l in script.split("\n") if re.match(r"^Object\.assign\(I18N\.(en|uk|ru),\{", l)]
    tr = re.search(r"^function tr\(key,vars=\{\}\)\{.*\}$", script, re.M).group(0)
    return script, i18n, task_copy, task_fn, assigns, tr


def decode(raw):
    return json.loads('"' + raw + '"')


def parse_tables(i18n, assigns):
    starts = [i18n.index(f"\n {lang}:{{") for lang in LOCALES] + [len(i18n)]
    tables = {lang: {} for lang in LOCALES}
    for n, lang in enumerate(LOCALES):
        for k, v in PAIR.findall(i18n[starts[n]:starts[n + 1]]):
            require(decode(k) not in tables[lang], f"{lang} duplicate key {decode(k)}")
            tables[lang][decode(k)] = decode(v)
    for line in assigns:
        lang = line[len("Object.assign(I18N."):][:2]
        for k, v in PAIR.findall(line):
            tables[lang][decode(k)] = decode(v)
    return tables


def referenced_keys(html, script):
    keys = set(re.findall(r'data-i18n(?:-placeholder|-title|-aria-label)?="([^"]+)"', html)) | set(re.findall(r'data-help="([^"]+)"', html))
    # tr('literal') calls; prefixes such as tr('stage.'+st) are dynamic families, not literal keys.
    keys |= {m.group(2) for m in re.finditer(r"""\btr\((['"])([A-Za-z0-9_.]+)\1(?!\s*\+)""", script) if not m.group(2).endswith(".")}
    keys |= set(re.findall(r"""\btr\([a-zA-Z_.]+\?'([A-Za-z0-9_.]+)':'[A-Za-z0-9_.]+'\)""", script))
    keys |= set(re.findall(r"""\btr\([a-zA-Z_.]+\?'[A-Za-z0-9_.]+':'([A-Za-z0-9_.]+)'\)""", script))
    return keys


def parity_problems(tables, referenced):
    """Return a list of human-readable parity problems (empty when the locales are in sync)."""
    problems = []
    en = tables["en"]
    for key in sorted(referenced - set(en)):
        problems.append(f"canonical key {key} is referenced by the dashboard but missing from EN")
    for lang in ("uk", "ru"):
        cur = tables[lang]
        for key in sorted(set(en) - set(cur)):
            problems.append(f"{lang} missing canonical key {key}")
        for key in sorted(set(cur) - set(en)):
            problems.append(f"{lang} has key {key} that is not in EN")
        for key in sorted(set(en) & set(cur)):
            if set(PLACEHOLDER.findall(en[key])) != set(PLACEHOLDER.findall(cur[key])):
                problems.append(f"{lang} {key} placeholders differ from EN")
            if cur[key] == en[key] and key not in SAME_AS_EN:
                problems.append(f"{lang} {key} is an untranslated EN fallback: {en[key]!r}")
            if FOREIGN_LETTERS[lang].search(cur[key]):
                problems.append(f"{lang} {key} mixes in letters from the other locale: {cur[key]!r}")
    for lang in LOCALES:
        for key, value in tables[lang].items():
            if not value.strip():
                problems.append(f"{lang} {key} is empty")
    return problems


def hardcoded_fallbacks(script):
    code = script[script.index("function taskCopy("):]
    code = "\n".join(l for l in code.split("\n") if not l.startswith("Object.assign(I18N."))
    hits = []
    for text in KNOWN_FALLBACKS:
        for pattern in ("'" + text + "'", ">" + text + "<", "'" + text + "</", "+'" + text):
            if pattern in code:
                hits.append(text)
                break
    return hits


def static_checks(html):
    script, i18n, task_copy, _, assigns, _ = extract(html)
    tables = parse_tables(i18n, assigns)
    referenced = referenced_keys(html, script)
    require(len(tables["en"]) > 900 and len(referenced) > 600, "locale tables / references not found")
    problems = parity_problems(tables, referenced)
    require(not problems, "locale parity problems:\n  " + "\n  ".join(problems[:60]))
    stale = sorted(k for k in SAME_AS_EN if k not in tables["en"])
    require(not stale, f"SAME_AS_EN allowlist has unknown keys: {stale}")
    hits = hardcoded_fallbacks(script)
    require(not hits, f"hardcoded EN UI strings bypass tr(): {hits}")
    # TASK_COPY (roadmap cards) must cover the same task ids in every locale.
    ids = {lang: set(re.findall(r'^  "([a-z0-9-]+)":\[', task_copy.split(f"\n {lang}:{{", 1)[1].split("\n }", 1)[0], re.M)) for lang in LOCALES}
    require(ids["en"] and ids["uk"] == ids["en"] and ids["ru"] == ids["en"], "TASK_COPY ids out of parity")

    # Self-test: the checker must catch a missing canonical key, a missing referenced key,
    # a cross-locale fallback, a placeholder drift and mixed-in letters.
    def mutated(fn):
        copy = {lang: dict(t) for lang, t in tables.items()}
        fn(copy)
        return parity_problems(copy, referenced)
    sample = "toast.jobCreated"
    require(any("ru missing canonical key " + sample in p for p in mutated(lambda t: t["ru"].pop(sample))), "checker missed a missing RU key")
    require(any("uk missing canonical key " + sample in p for p in mutated(lambda t: t["uk"].pop(sample))), "checker missed a missing UK key")
    require(any("missing from EN" in p for p in mutated(lambda t: [t[l].pop("action.close") for l in LOCALES])), "checker missed a missing referenced key")
    require(any("untranslated EN fallback" in p for p in mutated(lambda t: t["uk"].__setitem__(sample, t["en"][sample]))), "checker missed an EN fallback")
    require(any("placeholders differ" in p for p in mutated(lambda t: t["ru"].__setitem__("toast.armAssigned", "назначено"))), "checker missed placeholder drift")
    require(any("mixes in letters" in p for p in mutated(lambda t: t["uk"].__setitem__(sample, "Задача создана, ы"))), "checker missed RU letters in UK")
    require(hardcoded_fallbacks(script + "\ntoast('Job created')") == ["Job created"], "checker missed a hardcoded EN string")
    return script, i18n, task_copy, assigns, tables, referenced


HARNESS = r"""
%(i18n)s
%(task_copy)s
%(assigns)s
let LANG='en';
%(task_fn)s
%(tr)s
const shell=%(shell)s, keys=%(keys)s, out={};
for(const lang of ['en','uk','ru']){
 LANG=lang;
 const vars={n:3,error:'E',arm:'treatment',result:'promote',stage:'qa',name:'Scout',term:'hook'};
 out[lang]={
  keys:Object.keys(I18N[lang]),
  shell:shell.map(k=>[k,tr(k)]),
  rendered:keys.map(k=>[k,tr(k,vars)]),
  tasks:Object.keys(TASK_COPY.en).map(id=>{const c=taskCopy({id,title:'RAW-'+id,description:''});return [id,c.title,c.description]}),
  missingFallsBack:tr('fixture.missingKey')
 };
}
process.stdout.write(JSON.stringify(out));
"""


def fixture_checks(out, tables, shell_keys):
    for lang in LOCALES:
        got = out[lang]
        require(set(got["keys"]) == set(tables[lang]), f"{lang} Node table differs from the static parse")
        require(got["missingFallsBack"] == "fixture.missingKey", "tr() fallback contract changed")
        values = dict(got["rendered"])
        for key, value in got["shell"] + got["rendered"]:
            require(value != key, f"{lang} renders raw key {key}")
            require(not PLACEHOLDER.search(value), f"{lang} {key} leaves an unresolved placeholder: {value!r}")
        for task_id, title, description in got["tasks"]:
            require(not title.startswith("RAW-") and description.strip(), f"{lang} roadmap card {task_id} not localized")
        if lang == "en":
            continue
        text = "\n".join(v for _, v in got["shell"] + got["rendered"]) + "\n" + "\n".join(t + "\n" + d for _, t, d in got["tasks"])
        require(not FOREIGN_LETTERS[lang].search(text), f"{lang} fixture mixes in letters from the other locale")
        for key, value in got["shell"] + got["rendered"]:
            if key in SAME_AS_EN:
                continue
            require(value != dict(out["en"]["rendered"] + out["en"]["shell"])[key], f"{lang} fixture shows EN fallback for {key}: {value!r}")
        rendered_values = set(values.values()) | {v for _, v in got["shell"]}
        leaked = [s for s in KNOWN_FALLBACKS + KNOWN_EN_LEFTOVERS if s.strip() in rendered_values]
        require(not leaked, f"{lang} fixture contains known EN fallback strings: {leaked}")
        for _, title, description in got["tasks"]:
            require(title not in [t for _, t, _ in out["en"]["tasks"]], f"{lang} roadmap card falls back to EN: {title}")


def main():
    html = HTML.read_text(encoding="utf-8")
    script, i18n, task_copy, assigns, tables, referenced = static_checks(html)
    print(f"Locale parity static checks passed ({len(tables['en'])} canonical keys x EN/UK/RU, {len(referenced)} referenced)")
    node = shutil.which("node")
    if not node:
        if os.environ.get("FACTORYOS_REQUIRE_NODE") == "1":
            raise SystemExit("node is required for the locale fixture check")
        print("SKIPPED locale fixture check: node is not installed (CI runs it with FACTORYOS_REQUIRE_NODE=1)")
        return
    _, _, _, task_fn, _, tr = extract(html)
    shell = sorted(set(re.findall(r'data-i18n(?:-placeholder|-title|-aria-label)?="([^"]+)"', html)))
    program = HARNESS % {"i18n": i18n, "task_copy": task_copy, "assigns": "\n".join(assigns), "task_fn": task_fn, "tr": tr,
                         "shell": json.dumps(shell), "keys": json.dumps(sorted(referenced))}
    result = subprocess.run([node, "-"], input=program, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise SystemExit(f"locale harness failed:\n{result.stderr[-2000:]}")
    fixture_checks(json.loads(result.stdout), tables, shell)
    print(f"Locale fixture checks passed ({len(shell)} shell labels, {len(referenced)} rendered keys, roadmap cards; no raw keys or EN fallbacks in UK/RU)")


if __name__ == "__main__":
    try:
        main()
        # T-594 sidebar regression runs inside this CI step: the worker token cannot edit the workflow.
        import test_navigation
        test_navigation.main()
        # T-595 drawer resize/overflow regression, same reason.
        import test_drawers
        test_drawers.main()
    except AssertionError as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
