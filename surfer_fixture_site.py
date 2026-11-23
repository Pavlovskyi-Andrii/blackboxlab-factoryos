"""T-724: a small deterministic site for the Surfer action self-test (loopback only, no network).

Pages: a login form (optionally followed by an SMS-code step), a two-step form, a file upload, an account page with a
delete button and a payment button, a captcha-like wall, a "show password" toggle, a link to another site.
``site.events`` records what the site really received, so a test can prove that a step did or did not happen.
"""
from __future__ import annotations

import html
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

USERNAME, PASSWORD, SMS_CODE = "owner@example.test", "fixture-Passw0rd!", "424242"
COOKIE = "fos_fixture=signed-in-7f3a"


def _page(title: str, body: str) -> bytes:
    return ("<!doctype html><html><head><meta charset='utf-8'><title>%s</title></head><body><main><h1>%s</h1>%s"
            "</main></body></html>" % (title, title, body)).encode("utf-8")


INDEX = """<p>Fixture site for the Surfer self-test.</p>
<nav><a href="/login">Sign in</a> <a href="/wizard">Start the form</a> <a href="/upload">Upload a file</a>
<a href="/account">Account</a> <a href="/captcha">Captcha page</a> <a href="/show">Password toggle</a>
<a href="https://other.example/landing">Partner site</a></nav>"""

LOGIN = """<form method="post" action="/login%s"><label>Email <input type="email" name="username"
autocomplete="username"></label><label>Password <input type="password" name="password"
autocomplete="current-password"></label><button type="submit">Sign in</button></form>%s"""

# In-page navigation like GitHub or a single-page app: the URL changes a moment after the click, no new page load.
SOFT = """<p>Soft navigation page.</p><a id="soft" href="/soft/next">Next section</a>
<script>document.getElementById('soft').addEventListener('click', function (e) { e.preventDefault();
setTimeout(function () { history.pushState({}, '', '/soft/next'); document.querySelector('h1').textContent = 'Next section'; }, 1200);
});</script>"""
# A button whose script never returns (a busy loop): the page's main thread is stuck, like a hung site.
BUSY = """<p>Busy page.</p><button id="freeze" type="button">Freeze</button>
<script>document.getElementById('freeze').addEventListener('click', function () {
var t = Date.now(); while (Date.now() - t < 600000) {} });</script>"""
CODE = """<p>We sent a verification code to your phone. Enter the code.</p><form method="post" action="/login/code">
<label>Code <input type="text" name="otp" autocomplete="one-time-code" inputmode="numeric" maxlength="6"></label>
<button type="submit">Continue</button></form>"""

ACCOUNT = """<p id="who">Signed in as %s</p>
<form method="post" action="/account/delete"><button type="submit" class="btn btn-danger">Delete account</button></form>
<form method="post" action="/pay"><button type="submit">Pay now</button></form>
<form method="post" action="/account/note"><label>Note <input type="text" name="note"></label>
<button type="submit">Save</button></form>
<a href="/wizard">Start the form</a>"""

WIZARD_1 = """<form method="post" action="/wizard"><label>Full name <input type="text" name="name" required></label>
<label>Plan <select name="plan"><option value="free">Free</option><option value="pro">Pro</option></select></label>
<button type="submit">Next</button></form>"""

WIZARD_2 = """<p>Step 2 of 2 for %s (%s)</p><form method="post" action="/wizard/finish">
<input type="hidden" name="name" value="%s"><input type="hidden" name="plan" value="%s">
<label><input type="checkbox" name="agree" value="yes"> I agree</label>
<label>Comment <textarea name="comment"></textarea></label><button type="submit">Save</button></form>"""

UPLOAD = """<form method="post" action="/upload" enctype="multipart/form-data">
<label>File <input type="file" name="file"></label><button type="submit">Upload</button></form>"""

CAPTCHA = """<p>Please confirm you are not a robot.</p><div class="g-recaptcha" data-sitekey="fixture"></div>
<form method="post" action="/captcha"><button type="submit">Continue</button></form>"""

SHOW = """<form method="post" action="/show"><label>Password <input type="password" id="pw" name="password"
autocomplete="current-password"></label>
<button type="button" id="toggle" onclick="var p=document.getElementById('pw');p.type=p.type==='password'?'text':'password';
document.getElementById('echo').textContent=p.value">Show</button><p id="echo"></p></form>"""


class FixtureSite:
    def __init__(self):
        self.events: list = []
        self.sms_step = False
        site = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def _send(self, body: bytes, status: int = 200, headers=()):
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                for key, value in headers:
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)

            def _redirect(self, to: str, headers=()):
                self._send(b"", 303, (("Location", to),) + tuple(headers))

            def _signed_in(self) -> bool:
                return COOKIE in (self.headers.get("Cookie") or "")

            def do_GET(self):
                path = urlsplit(self.path).path
                if path == "/":
                    self._send(_page("Fixture home", INDEX))
                elif path == "/login":
                    self._send(_page("Sign in", LOGIN % ("", "")))
                elif path == "/busy":
                    self._send(_page("Busy", BUSY))
                elif path in ("/soft", "/soft/next"):
                    self._send(_page("Soft navigation", SOFT))
                elif path == "/login/code":
                    self._send(_page("Verification code", CODE))
                elif path == "/account":
                    if not self._signed_in():
                        return self._redirect("/login")
                    self._send(_page("Account", ACCOUNT % USERNAME))
                elif path == "/wizard":
                    self._send(_page("Form step 1", WIZARD_1))
                elif path == "/upload":
                    self._send(_page("Upload", UPLOAD))
                elif path == "/captcha":
                    self._send(_page("Check", CAPTCHA))
                elif path == "/show":
                    self._send(_page("Password toggle", SHOW))
                elif path == "/done":
                    last = site.events[-1] if site.events else {}
                    self._send(_page("Done", "<p id='result'>%s</p>" % html.escape(str(last))))
                else:
                    self._send(_page("Not found", ""), 404)

            def do_POST(self):
                path = urlsplit(self.path).path
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if path == "/upload":
                    name = re.search(rb'filename="([^"]*)"', raw)
                    parts = raw.split(b"\r\n\r\n", 1)
                    size = len(parts[1].rsplit(b"\r\n--", 1)[0]) if len(parts) == 2 else 0
                    site.events.append({"event": "upload", "name": (name.group(1).decode() if name else ""),
                                        "bytes": size})
                    return self._redirect("/done")
                form = {k: v[0] for k, v in parse_qs(raw.decode("utf-8", "replace")).items()}
                if path == "/login":
                    ok = form.get("username") == USERNAME and form.get("password") == PASSWORD
                    site.events.append({"event": "login", "ok": ok})
                    if not ok:
                        return self._send(_page("Sign in", LOGIN % ("", "<p id='error'>Wrong email or password</p>")))
                    if site.sms_step:
                        return self._redirect("/login/code")
                    return self._redirect("/account", (("Set-Cookie", COOKIE + "; Path=/; HttpOnly"),))
                if path == "/login/code":
                    ok = form.get("otp") == SMS_CODE
                    site.events.append({"event": "code", "ok": ok})
                    if not ok:
                        return self._redirect("/login/code")
                    return self._redirect("/account", (("Set-Cookie", COOKIE + "; Path=/; HttpOnly"),))
                if path == "/wizard":
                    name, plan = html.escape(form.get("name", "")), html.escape(form.get("plan", ""))
                    return self._send(_page("Form step 2", WIZARD_2 % (name, plan, name, plan)))
                if path == "/wizard/finish":
                    site.events.append({"event": "wizard", "name": form.get("name", ""), "plan": form.get("plan", ""),
                                        "agree": form.get("agree", ""), "comment": form.get("comment", "")})
                    return self._redirect("/done")
                if path in ("/account/delete", "/pay", "/account/note", "/captcha", "/show"):
                    site.events.append({"event": path.strip("/").replace("/", "_"), **form})
                    return self._redirect("/done")
                self._send(_page("Not found", ""), 404)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_exc):
        self.server.shutdown()
        self.server.server_close()
