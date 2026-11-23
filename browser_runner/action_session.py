"""T-720: one live browser page that executes Surfer action commands, one at a time (EC2 worker side).

``ActionSession`` wraps a Playwright page and its context. Every command (open, goto, act, snapshot, the owner's
human_input / takeover_* / save_login) goes through ``execute`` and comes back as a plain dict: status, a snapshot of
the page (text + interactive elements with refs), a screenshot for the owner, and what the network guard stopped.

Safety, all on this side as well as on the server:
- every step is reviewed with ``action_policy.review`` against the element as it is *now*; a step that needs the owner
  and was not confirmed is not executed;
- a main-frame navigation outside the allowed sites never leaves the browser;
- values of secret fields are not read; every secret the session typed is replaced in whatever it reports;
- captcha / anti-bot / code prompts are reported (``waiting_human``), never solved.

No Playwright import here: the page and context are handed in, so tests drive it with a double. Python 3.9.
"""
from __future__ import annotations

import base64
import os
import re
import time
from urllib.parse import urljoin
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import action_policy as policy
from .playwright_executor import _READ_PAGE_JS, _challenge, _main_frame_navigation

VIEWPORT = {"width": 1280, "height": 800}
MAX_ELEMENTS = 200
MAX_TEXT = 30_000
MAX_SHOT_BYTES = 1_900_000
STEP_TIMEOUT_MS = 15_000
SELECTOR_RE = re.compile(r"^[^\x00-\x1f<>{};]{1,200}$")
try:  # the worker has Playwright; CI's page double does not
    from playwright.sync_api import TimeoutError as _PlaywrightTimeout
except Exception:  # pragma: no cover
    class _PlaywrightTimeout(Exception):
        pass
LINK_WAIT_MS = 4000  # how long a link click waits for in-page navigation
REF_RE = re.compile(r"^e[0-9]{1,6}$")
_CODE_TEXT_RE = re.compile(
    r"(verification code|security code|enter (?:the )?code|one[- ]time (?:code|password)|sms code|"
    r"код (?:из|з) (?:смс|sms)|код подтверждения|код підтвердження|введите код|введіть код|одноразов)", re.I)
# A code prompt needs a field that looks like the code box, not just any input (GitHub's "Go to file" box on a README
# that mentions "SMS code" was taken for a 2FA wall on the first live session, 2026-11-23).
_CODE_FIELD_RE = re.compile(r"(otp|totp|\bcode\b|sms|verif|\bpin\b|one[- ]time|код|kod)", re.I)


def code_prompt_on(text: str, elements: list) -> bool:
    """The page asks for a one-time code: a one-time-code field, or code wording plus a field that looks like the box."""
    if any(e.get("autocomplete") == "one-time-code" for e in elements):
        return True
    return bool(_CODE_TEXT_RE.search(text[:4000])) and any(
        e.get("kind") == "input" and e.get("type") != "password" and _CODE_FIELD_RE.search(str(e.get("name") or ""))
        for e in elements)


_SAFE_UPLOAD_TYPES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".txt", ".pdf", ".mp4", ".mov", ".csv"})

# Fixed scripts: no command input is ever concatenated into them (arguments are passed as data).
_PRELUDE = r"""
const SECRET_AC = ['current-password','new-password','one-time-code','cc-number','cc-csc','cc-exp','cc-exp-month',
  'cc-exp-year'];
const SECRET_NAME = /(pass(word|wd)?|secret|token|otp|totp|cvv|cvc|card.?num|iban|(^|[^a-z])pin([^a-z]|$))/i;
const txt = s => (s || '').replace(/\s+/g, ' ').trim();
const abs = u => { try { const x = new URL(u, location.href);
  if (x.protocol !== 'http:' && x.protocol !== 'https:') return '';
  return x.origin + x.pathname + (x.search.length <= 200 ? x.search : ''); } catch (e) { return ''; } };
function visible(el) {
  const r = el.getBoundingClientRect();
  if (r.width < 1 || r.height < 1) return false;
  const st = getComputedStyle(el);
  return st.visibility !== 'hidden' && st.display !== 'none' && st.opacity !== '0';
}
function labelOf(el, tag, type) {
  let s = el.getAttribute('aria-label') || '';
  if (!s) { const ids = (el.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean);
    s = ids.map(i => { const n = document.getElementById(i); return n ? n.innerText : ''; }).join(' '); }
  if (!s && el.labels && el.labels.length) s = Array.from(el.labels).map(l => { const c = l.cloneNode(true);
    c.querySelectorAll('select,textarea,input,button').forEach(x => x.remove()); return c.textContent; }).join(' ');
  if (!s && tag === 'input' && ['submit','button','reset'].includes(type)) s = el.value || '';
  if (!s && !['input','select','textarea'].includes(tag)) s = el.innerText || '';
  if (!s) s = el.getAttribute('placeholder') || el.getAttribute('title') || '';
  if (!s && el.querySelector) { const img = el.querySelector('img[alt],svg[aria-label]');
    if (img) s = img.getAttribute('alt') || img.getAttribute('aria-label') || ''; }
  if (!s && ['input','select','textarea'].includes(tag)) s = el.getAttribute('name') || '';
  return txt(s).slice(0, 160);
}
function describe(el) {
  const tag = el.tagName.toLowerCase();
  const role = (el.getAttribute('role') || '').toLowerCase();
  const form = el.form || (el.closest ? el.closest('form') : null);
  let type = (el.getAttribute('type') || '').toLowerCase();
  if (tag === 'button' && !type) type = form ? 'submit' : 'button';
  if (tag === 'input' && !type) type = 'text';
  const ac = (el.getAttribute('autocomplete') || '').toLowerCase();
  let kind = 'other';
  if (tag === 'a') kind = 'link';
  else if (tag === 'button' || role === 'button' || (tag === 'input' && ['submit','button','reset','image'].includes(type))) kind = 'button';
  else if (tag === 'select') kind = 'select';
  else if (tag === 'textarea') kind = 'textarea';
  else if (tag === 'input') kind = type === 'checkbox' ? 'checkbox' : type === 'radio' ? 'radio' : type === 'file' ? 'file' : 'input';
  else if (el.isContentEditable) kind = 'editable';
  else if (role === 'link') kind = 'link';
  else if (role === 'checkbox' || role === 'switch' || role === 'radio') kind = 'checkbox';
  const secret = el.hasAttribute('data-fos-secret') || (tag === 'input' && (type === 'password' ||
    SECRET_AC.includes(ac) || SECRET_NAME.test((el.getAttribute('name') || '') + ' ' + (el.id || ''))));
  const d = {ref: el.getAttribute('data-fos-ref') || '', kind: kind, tag: tag, type: type, role: role,
    name: labelOf(el, tag, type), autocomplete: ac,
    hint: txt([el.id, el.getAttribute('name'), el.getAttribute('data-testid'),
      typeof el.className === 'string' ? el.className : ''].filter(Boolean).join(' ')).slice(0, 200),
    disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true', required: !!el.required,
    secret: !!secret, submit: false};
  if (tag === 'a') d.href = abs(el.getAttribute('href') || '');
  if (form) {
    const pw = form.querySelectorAll('input[type=password]');
    const sb = form.querySelector('button[type=submit],button:not([type]),input[type=submit]');
    d.form = {action: abs(form.getAttribute('action') || location.href),
      method: (form.getAttribute('method') || 'get').toLowerCase(), has_password: pw.length > 0,
      has_new_password: pw.length > 1 || !!form.querySelector('input[autocomplete=new-password]'),
      has_payment: !!form.querySelector('input[autocomplete^=cc-]'),
      has_otp: !!form.querySelector('input[autocomplete=one-time-code]'),
      submit_label: sb ? labelOf(sb, sb.tagName.toLowerCase(), (sb.getAttribute('type') || 'submit').toLowerCase()) : ''};
    d.submit = (tag === 'button' && type === 'submit') || (tag === 'input' && (type === 'submit' || type === 'image'));
  }
  if (secret) d.filled = !!el.value;
  else if (kind === 'checkbox' || kind === 'radio') d.checked = tag === 'input' ? !!el.checked : el.getAttribute('aria-checked') === 'true';
  else if (kind === 'select') { const o = el.selectedOptions && el.selectedOptions[0]; d.value = o ? txt(o.text).slice(0, 120) : '';
    d.options = Array.from(el.options || []).slice(0, 40).map(x => ({value: String(x.value).slice(0, 120), label: txt(x.text).slice(0, 120)})); }
  else if (kind === 'input' || kind === 'textarea') d.value = String(el.value || '').slice(0, 200);
  else if (kind === 'editable') d.value = txt(el.innerText).slice(0, 200);
  return d;
}
"""

SNAPSHOT_JS = "(opts) => {" + _PRELUDE + r"""
  const SEL = 'a[href],button,input:not([type=hidden]),select,textarea,summary,[role=button],[role=link],' +
    '[role=checkbox],[role=switch],[role=radio],[role=tab],[role=menuitem],[role=option],[contenteditable=""],' +
    '[contenteditable=true],[onclick]';
  if (!window.__fosDoc) window.__fosDoc = 'd' + Math.random().toString(36).slice(2, 10);
  let seq = window.__fosSeq || 0;
  const out = [];
  let total = 0;
  const vh = window.innerHeight || 800;
  for (const el of document.querySelectorAll(SEL)) {
    const isFile = el.tagName === 'INPUT' && (el.getAttribute('type') || '').toLowerCase() === 'file';
    if (!isFile && !visible(el)) continue;
    total += 1;
    if (out.length >= opts.max) continue;
    if (!el.getAttribute('data-fos-ref')) { seq += 1; el.setAttribute('data-fos-ref', 'e' + seq); }
    const d = describe(el);
    const r = el.getBoundingClientRect();
    d.in_view = r.bottom > 0 && r.top < vh;
    out.push(d);
  }
  window.__fosSeq = seq;
  return {page_id: window.__fosDoc, elements: out, elements_total: total,
          scroll: {y: Math.round(window.scrollY), height: Math.round(document.documentElement.scrollHeight), view: vh}};
}"""

DESCRIBE_JS = "(el) => {" + _PRELUDE + "\n  return describe(el);\n}"

# The owner typed here (a code, or anything during a takeover): the field is a secret field from now on.
MARK_SECRET_JS = r"""() => { const el = document.activeElement;
  if (el && el !== document.body && el.setAttribute) { el.setAttribute('data-fos-secret', '1'); return true; }
  return false; }"""

# Where a code the owner received goes: the one-time-code field, else a short numeric/code-like field, else the
# focused field. Returns its ref ('' when there is none).
FIND_CODE_FIELD_JS = "() => {" + _PRELUDE + r"""
  const pick = () => {
    const fields = Array.from(document.querySelectorAll('input')).filter(visible).filter(el =>
      !['hidden','checkbox','radio','file','submit','button','password'].includes((el.getAttribute('type') || 'text').toLowerCase()));
    return fields.find(el => (el.getAttribute('autocomplete') || '') === 'one-time-code') ||
      fields.find(el => /(otp|totp|code|sms|verif|pin|token)/i.test((el.getAttribute('name') || '') + ' ' + (el.id || '') + ' ' + (el.getAttribute('placeholder') || ''))) ||
      fields.find(el => el.getAttribute('inputmode') === 'numeric' && Number(el.getAttribute('maxlength') || 99) <= 8) ||
      (document.activeElement && ['INPUT','TEXTAREA'].includes(document.activeElement.tagName) ? document.activeElement : null);
  };
  const el = pick();
  if (!el) return '';
  if (!el.getAttribute('data-fos-ref')) { window.__fosSeq = (window.__fosSeq || 0) + 1; el.setAttribute('data-fos-ref', 'e' + window.__fosSeq); }
  el.setAttribute('data-fos-secret', '1');
  return el.getAttribute('data-fos-ref');
}"""


class _Stop(Exception):
    def __init__(self, body: Dict[str, Any]):
        super().__init__(body.get("blocker") or body.get("status") or "stop")
        self.body = body


def _error_code(exc: BaseException) -> str:
    name = type(exc).__name__
    if name == "TimeoutError":
        return "element_timeout"
    net = re.search(r"net::(ERR_[A-Z_]{3,60})", str(exc))
    if net:
        return "net_" + net.group(1).lower()
    return "browser_runtime_" + re.sub(r"[^A-Za-z0-9_]", "", name)[:60]


class ActionSession:
    def __init__(self, page: Any, context: Any, *, loopback: bool = False, upload_dir: Optional[Path] = None,
                 clock: Callable[[], float] = time.monotonic):
        self.page, self.context = page, context
        self.loopback = loopback
        self.upload_dir = Path(upload_dir) if upload_dir else None
        self.clock = clock
        self.secrets: List[str] = []
        self.policy: Dict[str, Any] = {"allow": [], "extra_origins": [], "takeover": False}
        self.events: List[Dict[str, str]] = []
        self._step: Dict[str, Any] = {}
        context.route("**/*", self._guard)
        if hasattr(context, "route_web_socket"):
            context.route_web_socket("**/*", self._guard_ws)
        if hasattr(context, "on"):
            context.on("page", self._popup)
        try:
            page.set_default_timeout(STEP_TIMEOUT_MS)
        except Exception:
            pass

    # --- network guard ------------------------------------------------------------------------------------------
    def _allowed(self, url: str) -> bool:
        return policy.url_allowed(self.policy.get("allow") or (), url,
                                  extra_origins=self.policy.get("extra_origins") or (), loopback=self.loopback)

    def _guard(self, route: Any) -> None:
        request = route.request
        url = str(getattr(request, "url", "") or "")
        method = str(getattr(request, "method", "GET") or "GET").upper()
        scheme = url.split(":", 1)[0].lower()
        if scheme not in ("http", "https"):
            route.continue_()                              # data:, blob:, about: never leave the browser
            return
        navigation = _main_frame_navigation(request)
        if scheme == "http" and not (self.loopback and policy.host_of(url) == "127.0.0.1"):
            if navigation:
                self.events.append({"event": "insecure_navigation", "url": policy.log_url(url)})
            route.abort()
            return
        if navigation:
            if self.policy.get("takeover"):
                route.continue_()                          # the owner is driving (a login may pass through an SSO site)
                return
            if not self._allowed(url):
                self.events.append({"event": "left_allowlist", "url": policy.log_url(url)})
                route.abort()
                return
            if method not in ("GET", "HEAD"):
                entry = policy.match(self.policy.get("allow") or (), policy.host_of(url)) or {}
                if "submit" not in (entry.get("classes") or ()) and not self._step.get("confirmed"):
                    self.events.append({"event": "submit_not_allowed", "url": policy.log_url(url)})
                    route.abort()
                    return
            route.continue_()
            return
        if method in ("GET", "HEAD", "OPTIONS") or self.policy.get("takeover") or self._allowed(url):
            route.continue_()                              # sub-resources, and the allowed site's own XHR
            return
        route.abort()                                      # third-party beacons and writes: quietly dropped

    def _guard_ws(self, websocket: Any) -> None:
        url = str(getattr(websocket, "url", "") or "").replace("wss://", "https://", 1).replace("ws://", "http://", 1)
        if self._allowed(url) and hasattr(websocket, "connect_to_server"):
            websocket.connect_to_server()
        else:
            websocket.close()

    def _popup(self, new_page: Any) -> None:
        if new_page is self.page:
            return
        try:
            self.events.append({"event": "popup_closed", "url": policy.log_url(str(getattr(new_page, "url", "") or ""))})
            new_page.close()
        except Exception:
            pass

    # --- reading ------------------------------------------------------------------------------------------------
    def snapshot(self) -> Dict[str, Any]:
        page = self.page
        try:
            data = page.evaluate(SNAPSHOT_JS, {"max": MAX_ELEMENTS}) or {}
        except Exception:
            data = {}
        try:
            read = page.evaluate(_READ_PAGE_JS) or {}
        except Exception:
            read = {}
        elements = [e for e in (data.get("elements") or []) if isinstance(e, dict)][:MAX_ELEMENTS]
        for element in elements:
            if element.get("secret"):
                element.pop("value", None)
        text = str(read.get("text") or "")[:MAX_TEXT]
        try:
            title = str(page.title() or "")[:300]
        except Exception:
            title = str(read.get("title") or "")[:300]
        try:
            challenge = _challenge(page)
        except Exception:
            challenge = ""
        visible_password = any(e.get("type") == "password" and e.get("autocomplete") != "new-password"
                               for e in elements)
        code_prompt = code_prompt_on(text, elements)
        if not challenge and code_prompt:
            challenge = "2fa"
        return {"url": policy.safe_url(str(page.url or "")), "title": title, "text": text,
                "page_id": str(data.get("page_id") or "")[:20], "elements": elements,
                "elements_total": int(data.get("elements_total") or len(elements)),
                "scroll": data.get("scroll") if isinstance(data.get("scroll"), dict) else {},
                "markers": {"challenge": challenge, "login_wall": bool(visible_password),
                            "code_prompt": bool(code_prompt)}}

    def _screenshot(self) -> str:
        try:
            raw = self.page.screenshot(type="png", full_page=False, timeout=8000)
            if len(raw) > MAX_SHOT_BYTES:
                raw = self.page.screenshot(type="jpeg", quality=60, full_page=False, timeout=8000)
            return base64.b64encode(raw).decode() if raw and len(raw) <= MAX_SHOT_BYTES else ""
        except Exception:
            return ""

    # --- acting -------------------------------------------------------------------------------------------------
    def _locate(self, cmd: Dict[str, Any]) -> Any:
        ref, selector = str(cmd.get("ref") or ""), str(cmd.get("selector") or "")
        if ref:
            if not REF_RE.fullmatch(ref):
                raise _Stop({"status": "refused", "blocker": "bad_ref"})
            locator = self.page.locator('[data-fos-ref="%s"]' % ref)
        elif selector and SELECTOR_RE.fullmatch(selector):
            locator = self.page.locator(selector)
        else:
            raise _Stop({"status": "refused", "blocker": "ref_or_selector_required"})
        count = locator.count()
        if count == 0:
            raise _Stop({"status": "failed", "blocker": "stale_ref" if ref else "selector_matched_nothing"})
        if count > 1:
            raise _Stop({"status": "failed", "blocker": "selector_matched_several", "matches": count})
        return locator

    def _settle(self) -> None:
        for state, ms in (("domcontentloaded", 5000), ("networkidle", 2500)):
            try:
                self.page.wait_for_load_state(state, timeout=ms)
            except Exception:
                pass

    def _upload_path(self, cmd: Dict[str, Any]) -> str:
        raw = str(cmd.get("file_path") or "")
        if not raw or self.upload_dir is None:
            raise _Stop({"status": "refused", "blocker": "upload_file_missing"})
        try:
            root = self.upload_dir.resolve(strict=True)
            path = Path(raw).resolve(strict=True)
            path.relative_to(root)
        except (OSError, ValueError):
            raise _Stop({"status": "refused", "blocker": "upload_outside_staging_dir"})
        if not path.is_file() or path.suffix.lower() not in _SAFE_UPLOAD_TYPES:
            raise _Stop({"status": "refused", "blocker": "upload_file_type_disallowed"})
        return str(path)

    def _goto(self, cmd: Dict[str, Any]) -> Dict[str, Any]:
        url = str(cmd.get("url") or "")
        verdict = policy.review("goto", None, str(self.page.url or ""), self.policy.get("allow") or (), url=url,
                                extra_origins=self.policy.get("extra_origins") or (), loopback=self.loopback)
        confirmed = set(cmd.get("confirmed_reasons") or ())
        if verdict["decision"] == policy.DECISION_REFUSE or (not self._allowed(url) and "leaves_allowlist" not in confirmed):
            return {"status": "refused", "blocker": verdict["detail"] or "off_allowlist"}
        response = self.page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        self._settle()
        try:
            status = int(getattr(response, "status", 0) or 0)
        except (TypeError, ValueError):
            status = 0
        return {"status": "done", "http_status": status}

    def _act(self, cmd: Dict[str, Any]) -> Dict[str, Any]:
        action = str(cmd.get("action") or "")
        key = str(cmd.get("key") or "")
        value_from = str(cmd.get("value_from") or "")
        needs_element = action in ("click", "fill", "select", "check", "upload") or bool(
            cmd.get("ref") or (cmd.get("selector") and action != "wait_for"))
        locator, element = None, None
        if needs_element:
            locator = self._locate(cmd)
            element = locator.evaluate(DESCRIBE_JS) or {}
            expect = cmd.get("expect")
            if isinstance(expect, dict) and expect and policy.fingerprint(element) != expect:
                raise _Stop({"status": "failed", "blocker": "stale_ref", "element": element})
        verdict = policy.review(action, element, str(self.page.url or ""), self.policy.get("allow") or (), key=key,
                                value_from=value_from, has_value=cmd.get("value") not in (None, ""),
                                extra_origins=self.policy.get("extra_origins") or (), loopback=self.loopback)
        info = {"element": element, "review": {"klass": verdict["klass"], "reasons": verdict["reasons"]}}
        if verdict["decision"] == policy.DECISION_REFUSE:
            return dict(info, status="refused", blocker=verdict["detail"])
        confirmed = set(cmd.get("confirmed_reasons") or ())
        if set(verdict["reasons"]) - confirmed:
            return dict(info, status="needs_confirmation")
        self._step = {"confirmed": bool(verdict["reasons"]), "klass": verdict["klass"]}
        ms = STEP_TIMEOUT_MS
        if action == "click":
            before = str(self.page.url or "")
            locator.click(timeout=ms)
            href = str((element or {}).get("href") or "")
            if href and not href.startswith("#") and not href.lower().startswith("javascript:") \
                    and urljoin(before, href).split("#")[0] != before.split("#")[0]:
                # Sites with in-page navigation (GitHub, SPAs) change the URL after the click returns and never fire a
                # new load event: wait briefly for the URL to change so the snapshot shows the new page. "commit" so a
                # same-document change does not also wait for the old page's resources; _settle() follows.
                try:
                    self.page.wait_for_url(lambda url: str(url) != before, timeout=LINK_WAIT_MS, wait_until="commit")
                except _PlaywrightTimeout:
                    pass
        elif action == "fill":
            value = str(cmd.get("secret_value") if value_from else cmd.get("value") or "")
            if value_from:
                if not value:
                    return dict(info, status="failed", blocker="vault_value_unavailable")
                if value_from.endswith("#password"):
                    self.secrets.append(value)             # never reported back, even if the page shows it
            locator.fill(value, timeout=ms)
        elif action == "select":
            wanted = str(cmd.get("value") or "")
            options = (element or {}).get("options") or []
            if any(o.get("value") == wanted for o in options) or not options:
                locator.select_option(value=wanted, timeout=ms)
            else:
                locator.select_option(label=wanted, timeout=ms)
        elif action == "check":
            locator.set_checked(str(cmd.get("value", "true")).lower() not in ("false", "0", "off", "no", ""), timeout=ms)
        elif action == "upload":
            locator.set_input_files(self._upload_path(cmd), timeout=ms)
        elif action == "press":
            if locator is not None:
                locator.press(key, timeout=ms)
            else:
                self.page.keyboard.press(key)
        elif action == "scroll":
            if locator is not None:
                locator.scroll_into_view_if_needed(timeout=ms)
            else:
                self.page.mouse.wheel(0, -700 if str(cmd.get("value") or "down").lower() == "up" else 700)
        elif action == "wait_for":
            selector, text = str(cmd.get("selector") or ""), str(cmd.get("value") or "")
            if selector and SELECTOR_RE.fullmatch(selector):
                self.page.locator(selector).first.wait_for(state="visible", timeout=ms)
            elif text:
                self.page.get_by_text(text[:200]).first.wait_for(state="visible", timeout=ms)
            else:
                return dict(info, status="refused", blocker="selector_or_text_required")
        elif action == "back":
            self.page.go_back(wait_until="domcontentloaded", timeout=ms)
        if action in ("click", "press", "back", "select", "check"):
            self._settle()
        return dict(info, status="done")

    def _owner(self, kind: str, cmd: Dict[str, Any]) -> Dict[str, Any]:
        """Commands only the owner page can queue (the server checks who queued them)."""
        page = self.page
        if kind == "human_input":
            text = str(cmd.get("secret_value") or "")
            if not text:
                return {"status": "failed", "blocker": "empty_input"}
            self.secrets.append(text)
            ref = str(cmd.get("ref") or "") or str(page.evaluate(FIND_CODE_FIELD_JS) or "")
            if not REF_RE.fullmatch(ref):
                return {"status": "failed", "blocker": "no_field_for_the_code"}
            locator = page.locator('[data-fos-ref="%s"]' % ref)
            locator.fill(text, timeout=STEP_TIMEOUT_MS)
            if cmd.get("submit"):
                locator.press("Enter", timeout=STEP_TIMEOUT_MS)
        elif kind == "takeover_click":
            x, y = float(cmd.get("x") or 0), float(cmd.get("y") or 0)
            if not (0 <= x <= VIEWPORT["width"] and 0 <= y <= VIEWPORT["height"]):
                return {"status": "refused", "blocker": "click_outside_view"}
            page.mouse.click(x, y)
        elif kind == "takeover_type":
            text = str(cmd.get("secret_value") or "")
            if text:
                self.secrets.append(text)
                page.evaluate(MARK_SECRET_JS)
                page.keyboard.type(text)
        elif kind == "takeover_key":
            if str(cmd.get("key") or "") not in policy.KEYS:
                return {"status": "refused", "blocker": "key_not_allowed"}
            page.keyboard.press(str(cmd["key"]))
        elif kind == "takeover_scroll":
            page.mouse.wheel(0, max(-2000, min(2000, int(cmd.get("dy") or 0))))
        else:
            return {"status": "failed", "blocker": "unknown_command"}
        self._settle()
        return {"status": "done"}

    def execute(self, cmd: Dict[str, Any]) -> Dict[str, Any]:
        """Run one command. Never raises; never returns a secret."""
        self.events = []
        self._step = {}
        raw = cmd.get("policy") if isinstance(cmd.get("policy"), dict) else {}
        kind = str(cmd.get("kind") or "")
        owner_kind = kind in ("human_input", "takeover_click", "takeover_type", "takeover_key", "takeover_scroll")
        self.policy = {"allow": [e for e in (raw.get("allow") or []) if isinstance(e, dict)],
                       "extra_origins": [str(o) for o in (raw.get("extra_origins") or [])][:20],
                       "takeover": bool(raw.get("takeover")) and owner_kind}
        storage_state = None
        try:
            if kind in ("open", "goto"):
                body = self._goto(cmd)
            elif kind == "act":
                body = self._act(cmd)
            elif kind == "snapshot":
                body = {"status": "done"}
            elif kind == "save_login":
                storage_state = self.context.storage_state()
                body = {"status": "done"}
            elif owner_kind:
                body = self._owner(kind, cmd)
            else:
                body = {"status": "failed", "blocker": "unknown_command"}
        except _Stop as stop:
            body = dict(stop.body)
        except Exception as exc:                            # no raw browser errors: they can carry URLs and DOM
            body = {"status": "failed", "blocker": _error_code(exc)}
        left = [e for e in self.events if e["event"] in ("left_allowlist", "insecure_navigation", "submit_not_allowed")]
        if left and body.get("status") in ("done", "failed"):
            body.update(status="blocked", blocker=left[0]["event"], redirect_to=left[0]["url"])
            try:                                            # the refused navigation left Chromium's error page
                if not str(self.page.url or "").startswith("http"):
                    self.page.go_back(wait_until="domcontentloaded", timeout=5000)
            except Exception:
                pass
        body["snapshot"] = self.snapshot()
        challenge = body["snapshot"]["markers"]["challenge"]
        if challenge and body.get("status") == "done" and not owner_kind and kind != "save_login":
            body.update(status="waiting_human", blocker=challenge)
        body["events"] = list(self.events)[:20]
        body["screenshot_b64"] = self._screenshot()
        body = policy.scrub(body, self.secrets)
        if storage_state is not None:
            body["storage_state"] = storage_state           # only for the encrypted vault; the server never logs it
        return body


def staging_name(name: str) -> str:
    """A safe file name for an upload staged on the worker."""
    base = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(str(name or "file")))[:80].lstrip(".") or "file"
    return base
