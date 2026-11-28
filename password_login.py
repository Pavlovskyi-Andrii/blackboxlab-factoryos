"""Password sign-in identifiers: the owner may type the FACTORY_USER login or an owner email; the password is unchanged.

Owner emails come from FACTORY_GOOGLE_OWNER_EMAILS (the same list that makes a Google account the owner) and the
optional FACTORY_OWNER_EMAILS. An email never replaces the password: it only names the same owner account.
"""
import hmac


def parse_emails(*raw_lists: str) -> set:
    """Comma-separated env values -> a set of trimmed, lower-case emails (entries without "@" are ignored)."""
    out = set()
    for raw in raw_lists:
        for item in (raw or "").split(","):
            item = item.strip().lower()
            if "@" in item:
                out.add(item)
    return out


def identifier_matches(username: str, factory_user: str, owner_emails) -> bool:
    """True when `username` is the configured login (exact, as before) or one of the owner emails (case-insensitive)."""
    username = username or ""
    user_ok = bool(factory_user) and hmac.compare_digest(username.strip().encode("utf-8"), factory_user.encode("utf-8"))
    typed = username.strip().lower()
    email_ok = False
    if "@" in typed:
        for email in owner_emails or ():                 # constant-time per entry, no early exit
            email_ok |= hmac.compare_digest(typed.encode("utf-8"), str(email).encode("utf-8"))
    return user_ok or email_ok


def password_login_ok(username: str, password: str, factory_user: str, factory_password: str, owner_emails) -> bool:
    """The full check behind POST /login. An unset FACTORY_PASSWORD never lets anyone in."""
    if not factory_password:
        return False
    password_ok = hmac.compare_digest((password or "").encode("utf-8"), factory_password.encode("utf-8"))
    return identifier_matches(username, factory_user, owner_emails) and password_ok
