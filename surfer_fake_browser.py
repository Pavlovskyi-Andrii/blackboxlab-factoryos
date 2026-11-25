"""T-720/T-724: a browser double for the Surfer action tests (CI has no Chromium).

``FakePlaywright`` gives ``ActionRunner`` a page that behaves like ``surfer_fixture_site`` without HTTP or JavaScript:
the same pages, forms and outcomes, modelled in Python. Requests still pass through the context's route handler, so
the network guard of ``ActionSession`` is exercised for real. ``site.events`` records what the "site" received.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from browser_runner import action_session as session_module
from browser_runner.playwright_executor import _READ_PAGE_JS
import surfer_fixture_site as fixture

ORIGIN = "https://shop.example"
PNG = b"\x89PNG\r\n\x1a\n" + b"fake-shot" * 4
PlaywrightTimeoutError = type("TimeoutError", (Exception,), {})


def _el(kind: str, name: str, **extra: Any) -> Dict[str, Any]:
    base = {"kind": kind, "name": name, "tag": {"link": "a", "button": "button", "select": "select",
                                                "textarea": "textarea"}.get(kind, "input"),
            "type": "", "role": "", "autocomplete": "", "hint": "", "disabled": False, "required": False,
            "secret": False, "submit": False}
    base.update(extra)
    return base


def _form(action: str, label: str, **flags: Any) -> Dict[str, Any]:
    return {"action": ORIGIN + action, "method": "post", "has_password": False, "has_new_password": False,
            "has_payment": False, "has_otp": False, "submit_label": label, **flags}


class FakeSite:
    """Server-side state of the modelled site."""

    def __init__(self):
        self.events: List[dict] = []
        self.sms_step = False
        self.signed_in = False
        self.wizard: Dict[str, str] = {}

    def dom(self, path: str) -> Dict[str, Any]:
        link = lambda name, href: _el("link", name, href=href if "://" in href else ORIGIN + href)  # noqa: E731
        if path == "/":
            return {"title": "Fixture home", "text": "Fixture site for the Surfer self-test.", "elements": [
                link("Sign in", "/login"), link("Start the form", "/wizard"), link("Upload a file", "/upload"),
                link("Account", "/account"), link("Captcha page", "/captcha"),
                link("Partner site", "https://other.example/landing")]}
        if path == "/login":
            form = _form("/login", "Sign in", has_password=True)
            return {"title": "Sign in", "text": "Email Password", "elements": [
                _el("input", "Email", type="email", autocomplete="username", form=form, css="input[name=username]"),
                _el("input", "Password", type="password", autocomplete="current-password", secret=True, form=form,
                    css="input[name=password]"),
                _el("button", "Sign in", type="submit", submit=True, form=form, post="/login")]}
        if path == "/login/code":
            form = _form("/login/code", "Continue", has_otp=True)
            return {"title": "Verification code", "text": "We sent a verification code to your phone. Enter the code.",
                    "elements": [_el("input", "Code", type="text", autocomplete="one-time-code", secret=True,
                                     form=form, css="input[name=otp]"),
                                 _el("button", "Continue", type="submit", submit=True, form=form, post="/login/code")]}
        if path == "/account":
            return {"title": "Account", "text": "Signed in as " + fixture.USERNAME, "elements": [
                _el("button", "Delete account", type="submit", submit=True, hint="btn btn-danger",
                    form=_form("/account/delete", "Delete account"), post="/account/delete", css="button.btn-danger"),
                _el("button", "Pay now", type="submit", submit=True, form=_form("/pay", "Pay now"), post="/pay"),
                _el("input", "Note", type="text", form=_form("/account/note", "Save"), css="input[name=note]"),
                _el("button", "Save", type="submit", submit=True, form=_form("/account/note", "Save"),
                    post="/account/note"),
                link("Start the form", "/wizard")]}
        if path == "/wizard":
            form = _form("/wizard", "Next")
            return {"title": "Form step 1", "text": "Full name Plan", "elements": [
                _el("input", "Full name", type="text", required=True, form=form, css="input[name=name]"),
                _el("select", "Plan", form=form, css="select[name=plan]",
                    options=[{"value": "free", "label": "Free"}, {"value": "pro", "label": "Pro"}]),
                _el("button", "Next", type="submit", submit=True, form=form, post="/wizard")]}
        if path == "/wizard/2":
            form = _form("/wizard/finish", "Save")
            return {"title": "Form step 2", "text": "Step 2 of 2 for " + self.wizard.get("name", ""), "elements": [
                _el("checkbox", "I agree", type="checkbox", form=form, css="input[name=agree]"),
                _el("textarea", "Comment", form=form, css="textarea[name=comment]"),
                _el("button", "Save", type="submit", submit=True, form=form, post="/wizard/finish")]}
        if path == "/upload":
            form = _form("/upload", "Upload")
            return {"title": "Upload", "text": "File", "elements": [
                _el("file", "File", type="file", form=form, css="input[type=file]"),
                _el("button", "Upload", type="submit", submit=True, form=form, post="/upload")]}
        if path == "/captcha":
            return {"title": "Check", "text": "Please confirm you are not a robot.", "captcha": True, "elements": [
                _el("button", "Continue", type="submit", submit=True, form=_form("/captcha", "Continue"),
                    post="/captcha")]}
        if path == "/done":
            return {"title": "Done", "text": str(self.events[-1] if self.events else {}), "elements": []}
        return {"title": "Not found", "text": "", "elements": []}

    def post(self, path: str, form: Dict[str, Any]) -> str:
        """Handle a form POST; returns the path the browser lands on."""
        if path == "/login":
            ok = form.get("Email") == fixture.USERNAME and form.get("Password") == fixture.PASSWORD
            self.events.append({"event": "login", "ok": ok})
            if not ok:
                return "/login"
            if self.sms_step:
                return "/login/code"
            self.signed_in = True
            return "/account"
        if path == "/login/code":
            ok = form.get("Code") == fixture.SMS_CODE
            self.events.append({"event": "code", "ok": ok})
            self.signed_in = self.signed_in or ok
            return "/account" if ok else "/login/code"
        if path == "/wizard":
            self.wizard = {"name": str(form.get("Full name") or ""), "plan": str(form.get("Plan") or "free")}
            return "/wizard/2"
        if path == "/wizard/finish":
            self.events.append({"event": "wizard", **self.wizard, "agree": "yes" if form.get("I agree") else "",
                                "comment": str(form.get("Comment") or "")})
            return "/done"
        if path == "/upload":
            self.events.append({"event": "upload", "name": str(form.get("File") or "")})
            return "/done"
        self.events.append({"event": path.strip("/").replace("/", "_"),
                            **{k.lower(): v for k, v in form.items() if v not in ("", None, False)}})
        return "/done"


class FakeRequest:
    def __init__(self, url: str, method: str, navigation: bool = True):
        self.url, self.method, self._navigation = url, method, navigation
        self.frame = None

    def is_navigation_request(self) -> bool:
        return self._navigation


class FakeRoute:
    def __init__(self, request: FakeRequest):
        self.request, self.aborted = request, False

    def abort(self) -> None:
        self.aborted = True

    def continue_(self) -> None:
        pass


class FakeLocator:
    def __init__(self, page: "FakePage", selector: str):
        self.page, self.selector = page, selector

    def _matches(self) -> List[dict]:
        sel = self.selector
        if sel.startswith('[data-fos-ref="'):
            ref = sel.split('"')[1]
            return [e for e in self.page.elements if e.get("ref") == ref]
        if "g-recaptcha" in sel:                        # the challenge markers of the executor
            return [{}] if self.page.dom.get("captcha") else []
        if "one-time-code" in sel:
            return [e for e in self.page.elements if e.get("autocomplete") == "one-time-code"]
        return [e for e in self.page.elements if e.get("css") == sel]

    def count(self) -> int:
        return len(self._matches())

    @property
    def first(self) -> "FakeLocator":
        return self

    def _one(self) -> dict:
        found = self._matches()
        if not found:
            raise PlaywrightTimeoutError("Timeout exceeded")
        return found[0]

    def evaluate(self, script: str, _arg: Any = None) -> Any:
        assert script is session_module.DESCRIBE_JS
        return self.page.describe(self._one())

    def click(self, timeout: int) -> None:
        self.page.click(self._one())

    def fill(self, value: str, timeout: int) -> None:
        self._one()["_value"] = value
        self.page.focused = self._one()

    def select_option(self, *, timeout: int, value: Optional[str] = None, label: Optional[str] = None) -> None:
        element = self._one()
        options = element.get("options") or []
        element["_value"] = value if value is not None else next(o["value"] for o in options if o["label"] == label)

    def set_checked(self, checked: bool, timeout: int) -> None:
        self._one()["_value"] = bool(checked)

    def press(self, key: str, timeout: int) -> None:
        element = self._one()
        if key == "Enter" and element.get("form"):
            button = next(e for e in self.page.elements if e.get("post") and e["form"]["action"] == element["form"]["action"])
            self.page.click(button)

    def set_input_files(self, path: str, timeout: int) -> None:
        self._one()["_value"] = path.replace("\\", "/").rsplit("/", 1)[-1]

    def scroll_into_view_if_needed(self, timeout: int) -> None:
        self._one()

    def wait_for(self, *, state: str, timeout: int) -> None:
        self._one()


class _Keyboard:
    def __init__(self, page: "FakePage"):
        self.page = page

    def press(self, key: str) -> None:
        self.page.keys.append(key)
        if key == "Enter" and self.page.focused is not None and self.page.focused.get("form"):
            FakeLocator(self.page, '[data-fos-ref="%s"]' % self.page.focused["ref"]).press("Enter", 0)

    def type(self, text: str) -> None:
        if self.page.focused is not None:
            self.page.focused["_value"] = str(self.page.focused.get("_value") or "") + text


class _Mouse:
    def __init__(self, page: "FakePage"):
        self.page = page

    def click(self, x: float, y: float) -> None:
        """A takeover click: element N of the page sits at y = 100 * N (enough for the tests)."""
        index = int(y // 100) - 1
        if 0 <= index < len(self.page.elements):
            element = self.page.elements[index]
            if element["kind"] in ("input", "textarea"):
                self.page.focused = element
            else:
                self.page.click(element)

    def wheel(self, _dx: int, dy: int) -> None:
        self.page.scrolled += dy


class FakePage:
    def __init__(self, context: "FakeContext"):
        self.context, self.site = context, context.site
        self.url = "about:blank"
        self.dom: Dict[str, Any] = {"title": "", "text": "", "elements": []}
        self.elements: List[dict] = []
        self.focused: Optional[dict] = None
        self.keys: List[str] = []
        self.scrolled = 0
        self.history: List[str] = []
        self.seq = 0
        self.keyboard, self.mouse = _Keyboard(self), _Mouse(self)

    # --- navigation through the route guard -------------------------------------------------------------------
    def _request(self, url: str, method: str) -> bool:
        route = FakeRoute(FakeRequest(url, method))
        self.context.route_handler(route)
        return not route.aborted

    def _load(self, url: str) -> None:
        parts = urlsplit(url)
        self.url = url
        origin = f"{parts.scheme}://{parts.netloc}"
        path = parts.path or "/"
        if origin != ORIGIN:
            self.dom = {"title": "Other site", "text": "A page on another site.", "elements": []}
        elif path == "/account" and not self.site.signed_in:
            return self._load(ORIGIN + "/login")
        else:
            self.dom = self.site.dom(path)
        self.elements = [dict(e) for e in self.dom["elements"]]
        self.focused, self.seq = None, 0

    def goto(self, url: str, *, wait_until: str, timeout: int) -> Any:
        if not self._request(url, "GET"):
            raise RuntimeError("net::ERR_BLOCKED_BY_CLIENT at " + url)
        self.history.append(self.url)
        self._load(url)
        return type("Response", (), {"status": 200})()

    def wait_for_url(self, predicate, *, timeout: int, wait_until: str) -> None:
        """Navigation here is synchronous: the URL has changed by now or it never will."""
        self.waits = getattr(self, "waits", 0) + 1
        if not predicate(self.url):
            from browser_runner.action_session import _PlaywrightTimeout
            raise _PlaywrightTimeout("url did not change")

    def go_back(self, *, wait_until: str, timeout: int) -> None:
        if self.history:
            self._load(self.history.pop())

    def click(self, element: dict) -> None:
        if element["kind"] == "link":
            if self._request(element["href"], "GET"):
                self.history.append(self.url)
                self._load(element["href"])
        elif element.get("post"):
            action = element["form"]["action"]
            if self._request(action, "POST"):
                form = {e["name"]: e.get("_value") for e in self.elements
                        if e.get("form", {}).get("action") == action and not e.get("post")}
                self.history.append(self.url)
                self._load(ORIGIN + self.site.post(element["post"], form))

    # --- what the executor asks of a page ---------------------------------------------------------------------
    def set_default_timeout(self, _ms: int) -> None:
        pass

    def title(self) -> str:
        return self.dom["title"]

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self, selector)

    def get_by_text(self, text: str) -> FakeLocator:
        page = self

        class _Text(FakeLocator):
            def _matches(self) -> List[dict]:
                return [{}] if text in page.dom["text"] else []
        return _Text(self, text)

    def wait_for_load_state(self, _state: str, timeout: int) -> None:
        pass

    def describe(self, element: dict) -> dict:
        out = {k: v for k, v in element.items() if not k.startswith("_") and k not in ("post", "css")}
        value = element.get("_value")
        if out.get("secret"):
            out["filled"] = bool(value)
        elif out["kind"] in ("checkbox", "radio"):
            out["checked"] = bool(value)
        elif out["kind"] in ("input", "textarea", "select"):
            out["value"] = str(value or "")
        return out

    def evaluate(self, script: str, arg: Any = None) -> Any:
        if script is session_module.SNAPSHOT_JS:
            for element in self.elements:
                if not element.get("ref"):
                    self.seq += 1
                    element["ref"] = "e%d" % self.seq
            return {"page_id": "d" + str(abs(hash(self.url)) % 10**6), "elements_total": len(self.elements),
                    "elements": [self.describe(e) for e in self.elements[:arg["max"]]]}
        if script is _READ_PAGE_JS:
            shown = " ".join(str(e.get("_value")) for e in self.elements if e.get("_shown"))
            return {"title": self.dom["title"], "text": (self.dom["text"] + " " + shown).strip(), "links": []}
        if script is session_module.FIND_CODE_FIELD_JS:
            field = next((e for e in self.elements if e.get("autocomplete") == "one-time-code"), None)
            if field is None:
                return ""
            field["secret"] = True
            return field["ref"]
        if script is session_module.DOM_QUIET_JS:
            self.quiet_waits = getattr(self, "quiet_waits", 0) + 1
            return True
        if script is session_module.MARK_SECRET_JS:
            if self.focused is not None:
                self.focused["secret"] = True
            return self.focused is not None
        raise AssertionError("unexpected script")

    def screenshot(self, **_kwargs: Any) -> bytes:
        return PNG

    def close(self) -> None:
        pass


class FakeContext:
    def __init__(self, site: FakeSite, kwargs: dict):
        self.site, self.kwargs = site, kwargs
        self.route_handler = None
        self.closed = False
        if kwargs.get("storage_state"):
            site.signed_in = True                     # the saved login was restored

    def route(self, _pattern: str, handler: Any) -> None:
        self.route_handler = handler

    def route_web_socket(self, _pattern: str, _handler: Any) -> None:
        pass

    def on(self, _event: str, _handler: Any) -> None:
        pass

    def new_page(self) -> FakePage:
        self.page = FakePage(self)
        return self.page

    def storage_state(self) -> dict:
        return {"cookies": [{"name": "fos_fixture", "value": "signed-in-7f3a", "domain": "shop.example", "path": "/",
                             "expires": -1, "httpOnly": True, "secure": True, "sameSite": "Lax"}], "origins": []}

    def close(self) -> None:
        self.closed = True


class FakePlaywright:
    """``start_playwright`` for ActionRunner: ``FakePlaywright(site)`` is callable and returns itself."""

    def __init__(self, site: Optional[FakeSite] = None):
        self.site = site or FakeSite()
        self.chromium = self
        self.contexts: List[FakeContext] = []
        self.launches = self.stops = 0

    def __call__(self) -> "FakePlaywright":
        return self

    def launch(self, **kwargs: Any) -> "FakePlaywright":
        self.launches += 1
        self.launch_kwargs = kwargs
        return self

    def new_context(self, **kwargs: Any) -> FakeContext:
        context = FakeContext(self.site, kwargs)
        self.contexts.append(context)
        return context

    def close(self) -> None:
        pass

    def stop(self) -> None:
        self.stops += 1

    @property
    def page(self) -> FakePage:
        return self.contexts[-1].page
