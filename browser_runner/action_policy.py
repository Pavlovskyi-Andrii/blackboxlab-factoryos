"""T-720/T-721: the policy of Surfer action sessions. Pure Python, no I/O, Python 3.9 compatible.

The FactoryOS server (``surfer_actions.py``) and the EC2 executor (``browser_runner/action_session.py``) import the
same functions, so a step is classified twice from two descriptions of the element: what the agent saw in its
snapshot (server) and what is on the page right before the click (worker).

Owner 2026-11-22: inside the allowlist the Surfer acts by itself; payment, deleting, security settings, messages to
other people, publishing and anything outside the allowlist wait for the owner's confirmation of that step.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlsplit

ACTION_CLASSES = ("read", "navigate", "fill", "submit", "upload")
ACTIONS = ("click", "fill", "select", "check", "press", "upload", "scroll", "wait_for", "back", "goto")
KEYS = ("Enter", "Tab", "Escape", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "PageUp", "PageDown", "Home",
        "End", "Backspace", "Delete", "Space")
VAULT_REF_RE = re.compile(r"^vault:([a-z0-9][a-z0-9_.-]{0,39})/([\w.@+ -]{1,80})#(username|password)$")
PATTERN_RE = re.compile(r"^(?=.{4,100}$)[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$")
# A pattern covers a domain and its subdomains, so a shared suffix would allow every site under it.
_SHARED_SUFFIXES = frozenset({
    "co.uk", "org.uk", "com.ua", "org.ua", "net.ua", "in.ua", "kiev.ua", "com.au", "co.jp", "com.br", "com.tr",
    "co.in", "com.pl", "github.io", "gitlab.io", "onrender.com", "vercel.app", "netlify.app", "pages.dev",
    "web.app", "herokuapp.com", "blogspot.com", "wordpress.com", "google.com", "googleusercontent.com",
    "amazonaws.com", "cloudfront.net", "azurewebsites.net", "fly.dev", "workers.dev", "firebaseapp.com",
})

DECISION_ALLOW, DECISION_CONFIRM, DECISION_REFUSE = "allow", "confirm", "refuse"


def _rx(latin: str, cyrillic: str) -> "re.Pattern[str]":
    return re.compile(r"(?:\b(?:" + latin + r")\b)|(?:" + cyrillic + r")", re.I)


# Verbs: an element named like this does the thing, whatever kind of element it is.
_PAYMENT = _rx(
    r"pay|pay\s*now|buy|buy\s*now|purchase|checkout|check\s*out|place\s*(?:an?\s*|the\s*)?order|order\s*now|"
    r"subscribe|upgrade|donate|add\s*(?:a\s*)?card|top\s*up|add\s*funds|complete\s*order",
    r"оплат|купит|куплю|заказат|оформить\s*заказ|придбати|сплат|сплач|замовит|оформити\s*замовлення|"
    r"пополнит|поповнит|подписаться|підписатися|передплат")
_DELETE = _rx(
    r"delete|remove|destroy|erase|trash|deactivate|close\s*(?:my\s*|the\s*)?account|terminate|revoke|suspend|purge|"
    r"wipe|discard|unpublish|cancel\s*subscription|unsubscribe|reset\s*(?:all|data|account)|empty\s*trash",
    r"удал|стер[еэ]т|стира|видал|вилуч|деактив|закрыть\s*аккаунт|закрити\s*акаунт|снять\s*с\s*публикации|"
    r"зняти\s*з\s*публікації|очистить|очистити|отписаться|відписатися|сбросить|скинути")
_MESSAGING = _rx(
    r"send|send\s*message|message|reply|comment|invite|share|tweet|retweet|repost|contact\s*seller|respond|"
    r"post\s*comment|start\s*chat|write\s*(?:a\s*)?message|e-?mail\s*(?:us|them|seller)",
    r"отправ|написат|сообщен|ответит|комментир|пригласит|поделит|надісл|надіслати|повідомл|відповіс|коментув|"
    r"запросит|поділит|связаться|зв'язатися")
_PUBLISH = _rx(
    r"publish|post|go\s*live|release|deploy|manual\s*deploy|launch|submit\s*for\s*review|promote|boost|make\s*public",
    r"опублик|опублік|разместит|розмістит|выложит|викласти|запустит|задепло|продвин|просуну|поднять\s*объявление|"
    r"підняти\s*оголошення")
_SECURITY_VERB = _rx(
    r"log\s*out|sign\s*out|change\s*password|reset\s*password|set\s*password|update\s*password|change\s*e-?mail|"
    r"enable\s*2fa|disable\s*2fa|two[- ]factor|regenerate|rotate|create\s*(?:api\s*)?(?:key|token)|"
    r"generate\s*(?:api\s*)?(?:key|token)|new\s*(?:api\s*)?(?:key|token)|add\s*ssh\s*key|add\s*deploy\s*key|"
    r"authorize|grant\s*access|transfer\s*ownership|add\s*(?:member|collaborator)|change\s*role|"
    r"add\s*environment\s*variable|save\s*environment",
    r"выйти|вийти|сменить\s*пароль|змінити\s*пароль|изменить\s*пароль|сбросить\s*пароль|скинути\s*пароль|"
    r"двухфактор|двофактор|создать\s*(?:ключ|токен)|створити\s*(?:ключ|токен)|выдать\s*доступ|надати\s*доступ|"
    r"авторизовать|авторизувати|передать\s*права|передати\s*права")
# Section names: reading the page behind such a link is fine, pressing a button or submitting a form there is not.
_SECURITY_CONTEXT = _rx(
    r"password|passcode|2fa|mfa|security|api[\s_-]*keys?|access[\s_-]*tokens?|tokens?|secrets?|ssh[\s_-]*keys?|"
    r"deploy[\s_-]*keys?|recovery|permissions?|roles?|oauth|env(?:ironment)?(?:[\s_-]*var\w*)?|credentials?",
    r"парол|безопасн|безпек|токен|секрет|доступ")
_PAYMENT_CONTEXT = _rx(r"billing|payments?|invoices?|plans?|pricing|subscription|wallet|cards?",
                       r"платеж|платіж|оплат|тариф|счет|рахун|кошел|гаман")
_DANGER_HINT = re.compile(r"(?:^|[^a-z])(?:danger|destructive|delete|remove|trash|destroy)(?:[^a-z]|$)", re.I)
_PAY_HINT = re.compile(r"(?:^|[^a-z])(?:pay|buy|checkout|purchase|subscribe)(?:[^a-z]|$)", re.I)

REASONS = ("payment", "delete", "security", "messaging", "publish", "leaves_allowlist", "off_allowlist",
           "class_not_allowed", "unlabeled_control")


def host_of(url: str) -> str:
    try:
        return (urlsplit(str(url or "")).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def origin_of(url: str) -> str:
    try:
        parts = urlsplit(str(url or ""))
        host = (parts.hostname or "").lower().rstrip(".")
        if parts.scheme not in ("http", "https") or not host:
            return ""
        port = parts.port
    except ValueError:
        return ""
    default = 443 if parts.scheme == "https" else 80
    return "%s://%s%s" % (parts.scheme, host, "" if port in (None, default) else ":%d" % port)


def safe_url(url: str, limit: int = 500) -> str:
    """Origin + path + query for a snapshot (no credentials, no fragment), bounded."""
    try:
        parts = urlsplit(str(url or ""))
    except ValueError:
        return ""
    origin = origin_of(url)
    if not origin:
        return ""
    query = "?" + parts.query if parts.query and len(parts.query) <= 200 else ""
    return (origin + (parts.path or "/") + query)[:limit]


def log_url(url: str, limit: int = 300) -> str:
    """Origin + path for the audit log: a query can carry tokens."""
    try:
        path = urlsplit(str(url or "")).path or "/"
    except ValueError:
        return ""
    origin = origin_of(url)
    return (origin + path)[:limit] if origin else ""


def clean_pattern(raw: Any) -> str:
    """A domain pattern of the owner's allowlist: 'olx.ua' (covers subdomains). '' when it is not acceptable."""
    text = str(raw or "").strip().lower()
    if "://" in text:
        text = host_of(text)
    text = text.lstrip("*").lstrip(".").rstrip(".").split("/")[0]
    if not PATTERN_RE.fullmatch(text) or text in _SHARED_SUFFIXES or re.fullmatch(r"[0-9.]+", text):
        return ""
    return text


def clean_classes(raw: Any) -> List[str]:
    wanted = {str(c).strip().lower() for c in (raw if isinstance(raw, (list, tuple, set)) else [])}
    return [c for c in ACTION_CLASSES if c in wanted]


def match(allow: Iterable[Dict[str, Any]], host: str) -> Optional[Dict[str, Any]]:
    """The enabled allowlist entry for a host; the longest (most specific) pattern wins."""
    host = str(host or "").lower().rstrip(".")
    best = None
    for entry in allow or ():
        pattern = str(entry.get("pattern") or "")
        if not entry.get("enabled") or not pattern:
            continue
        if host == pattern or host.endswith("." + pattern):
            if best is None or len(pattern) > len(str(best.get("pattern") or "")):
                best = entry
    return best


def url_allowed(allow: Iterable[Dict[str, Any]], url: str, *, extra_origins: Iterable[str] = (),
                loopback: bool = False) -> bool:
    origin = origin_of(url)
    if not origin:
        return False
    if origin in set(extra_origins or ()):
        return True
    if not origin.startswith("https://") and not (loopback and host_of(url) == "127.0.0.1"):
        return False
    return match(allow, host_of(url)) is not None


def is_secret_field(el: Dict[str, Any]) -> bool:
    return bool(el.get("secret"))


def _text(el: Dict[str, Any]) -> str:
    return " ".join(str(el.get("name") or "").lower().split())[:300]


def _is_link(el: Dict[str, Any]) -> bool:
    return str(el.get("kind") or "") == "link" and bool(el.get("href"))


def action_class(action: str, el: Optional[Dict[str, Any]] = None, key: str = "") -> str:
    el = el or {}
    if action in ("scroll", "wait_for"):
        return "read"
    if action in ("back", "goto"):
        return "navigate"
    if action in ("fill", "select", "check"):
        return "fill"
    if action == "upload":
        return "upload"
    if action == "press":
        if key == "Enter":                            # Enter in a field submits its form or runs the page's handler
            return "navigate" if _is_link(el) else "submit"
        return "fill" if key in ("Backspace", "Delete", "Space") and el else "read"
    if action == "click":
        if _is_link(el):
            return "navigate"
        if el.get("submit") or str(el.get("type") or "") in ("submit", "image"):
            return "submit"
        if el.get("kind") in ("checkbox", "radio", "select", "input", "textarea", "editable", "file"):
            return "fill"
        return "submit" if _commit_words(_text(el)) else "navigate"
    return "submit"                                   # an unknown action is treated as the strongest class


_COMMIT = _rx(r"save|submit|send|create|apply|confirm|update|add|register|sign\s*up|continue|finish|done|ok|yes|"
              r"accept|agree|approve|import|upload|next|proceed",
              r"сохран|отправ|создат|применит|подтверд|обновит|добавит|зарегистр|продолжит|готово|принят|соглас|"
              r"далее|зберегти|надісл|створит|застосув|підтверд|оновит|додат|зареєстр|продовж|прийнят|погод|далі")


def _commit_words(text: str) -> bool:
    return bool(_COMMIT.search(text))


def _word_reasons(el: Dict[str, Any], *, verbs_only: bool) -> List[str]:
    text = _text(el)
    form = el.get("form") or {}
    target_path = ""
    for url in (el.get("href"), form.get("action")):
        try:
            target_path += " " + urlsplit(str(url or "")).path.replace("/", " ").replace("-", " ").replace("_", " ")
        except ValueError:
            pass
    blob = (text + " " + str(form.get("submit_label") or "").lower() + " " + target_path.lower()).strip()
    hint = str(el.get("hint") or "")
    out = []
    if _PAYMENT.search(blob) or form.get("has_payment") or (not text and _PAY_HINT.search(hint)):
        out.append("payment")
    if _DELETE.search(blob) or (not text and _DANGER_HINT.search(hint)):
        out.append("delete")
    if _SECURITY_VERB.search(blob) or form.get("has_new_password"):
        out.append("security")
    if _MESSAGING.search(blob):
        out.append("messaging")
    if _PUBLISH.search(blob):
        out.append("publish")
    if not verbs_only:
        if "security" not in out and _SECURITY_CONTEXT.search(blob):
            out.append("security")
        if "payment" not in out and _PAYMENT_CONTEXT.search(blob):
            out.append("payment")
    return out


def review(action: str, el: Optional[Dict[str, Any]], page_url: str, allow: Iterable[Dict[str, Any]], *,
           key: str = "", url: str = "", value_from: str = "", has_value: bool = False,
           extra_origins: Iterable[str] = (), loopback: bool = False) -> Dict[str, Any]:
    """Decide one step. Returns {decision: allow|confirm|refuse, klass, reasons, detail}.

    ``el`` is the element description (None for back/scroll/wait_for/goto and a bare key press);
    ``url`` is the target of ``goto``."""
    el = dict(el or {})
    allow = list(allow or ())
    extra = set(extra_origins or ())
    if action not in ACTIONS:
        return {"decision": DECISION_REFUSE, "klass": "submit", "reasons": [], "detail": "unknown_action"}
    klass = action_class(action, el, key)
    entry = match(allow, host_of(page_url))
    on_allowlist = entry is not None and url_allowed(allow, page_url, loopback=loopback)
    reasons: List[str] = []

    def out(decision: str, detail: str = "") -> Dict[str, Any]:
        return {"decision": decision, "klass": klass, "reasons": reasons, "detail": detail}

    # --- hard refusals: nothing the owner could usefully confirm -------------------------------------------
    if action in ("fill", "select", "check", "upload", "click") and not el:
        return out(DECISION_REFUSE, "element_required")
    if el.get("disabled") and action in ("click", "fill", "select", "check", "upload"):
        return out(DECISION_REFUSE, "element_disabled")
    if action == "press" and key not in KEYS:
        return out(DECISION_REFUSE, "key_not_allowed")
    if action == "upload" and el.get("kind") != "file":
        return out(DECISION_REFUSE, "not_a_file_input")
    if action == "fill":
        if el.get("kind") not in ("input", "textarea", "editable"):
            return out(DECISION_REFUSE, "not_a_text_field")
        if value_from:
            ref = VAULT_REF_RE.fullmatch(value_from)
            if not ref:
                return out(DECISION_REFUSE, "bad_vault_reference")
            if not on_allowlist or str(entry.get("login") or "") != "%s/%s" % (ref.group(1), ref.group(2)):
                return out(DECISION_REFUSE, "vault_login_not_bound_to_this_site")
            if ref.group(3) == "password" and str(el.get("type") or "") != "password":
                return out(DECISION_REFUSE, "vault_password_only_into_password_field")
            if ref.group(3) == "username" and (is_secret_field(el) or str(el.get("type") or "text") not in
                                               ("text", "email", "tel", "")):
                return out(DECISION_REFUSE, "vault_username_only_into_text_field")
        elif is_secret_field(el) and has_value:
            return out(DECISION_REFUSE, "secret_field_needs_vault_reference")
    elif value_from:
        return out(DECISION_REFUSE, "vault_reference_only_for_fill")

    # --- where does the step lead ---------------------------------------------------------------------------
    target = ""
    if action == "goto":
        target = url
    elif action == "click" and _is_link(el):
        target = str(el.get("href") or "")
    elif klass == "submit" and (el.get("form") or {}).get("action"):
        target = str(el["form"]["action"])
    if target and origin_of(target) and not url_allowed(allow, target, extra_origins=extra, loopback=loopback):
        reasons.append("leaves_allowlist")
    if not on_allowlist:
        if klass in ("fill", "submit", "upload"):
            reasons.append("off_allowlist")
    elif klass != "read" and klass not in (entry.get("classes") or ()):
        reasons.append("class_not_allowed")

    # --- what does the step do ------------------------------------------------------------------------------
    if action in ("click", "press") and el and klass in ("submit", "navigate"):
        subject = el
        if action == "press" and el.get("form"):
            # Enter in a field does what the form's submit button does; the field's own label says nothing about it.
            subject = {"name": (el.get("form") or {}).get("submit_label") or "", "form": el.get("form"),
                       "kind": "button"}
        words = _word_reasons(subject, verbs_only=_is_link(el))
        reasons.extend(r for r in words if r not in reasons)
        if action == "click" and not _is_link(el) and not _text(el) and el.get("kind") in ("button", "other"):
            reasons.append("unlabeled_control")
    elif action == "goto":
        words = _word_reasons({"href": url}, verbs_only=True)
        reasons.extend(r for r in words if r not in reasons)
    elif action in ("fill", "select", "check", "upload"):
        ac = str(el.get("autocomplete") or "")
        if ac == "new-password" or (el.get("form") or {}).get("has_new_password") and str(el.get("type")) == "password":
            reasons.append("security")
        if ac.startswith("cc-"):
            reasons.append("payment")
    reasons[:] = list(dict.fromkeys(reasons))
    return out(DECISION_CONFIRM if reasons else DECISION_ALLOW)


def fingerprint(el: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """What must still be true about the element when the worker acts on it (a changed page is `stale_ref`)."""
    el = el or {}
    form = el.get("form") or {}
    return {"kind": str(el.get("kind") or ""), "type": str(el.get("type") or ""),
            "name": " ".join(str(el.get("name") or "").split())[:200],
            "href": log_url(str(el.get("href") or "")), "form_action": log_url(str(form.get("action") or "")),
            "secret": "1" if el.get("secret") else ""}


def scrub(value: Any, secrets: Iterable[str]) -> Any:
    """Replace every secret the session typed in strings of a nested value."""
    needles = sorted({s for s in secrets or () if isinstance(s, str) and len(s) >= 3}, key=len, reverse=True)
    if not needles:
        return value

    def walk(item: Any) -> Any:
        if isinstance(item, str):
            for needle in needles:
                if needle in item:
                    item = item.replace(needle, "***")
            return item
        if isinstance(item, dict):
            return {k: walk(v) for k, v in item.items()}
        if isinstance(item, (list, tuple)):
            return [walk(v) for v in item]
        return item
    return walk(value)
