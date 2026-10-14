"""Custom tools exposed to Claude via the Anthropic tool-use schema.

Both tools only analyse the text they are given. They never visit a URL, resolve DNS,
open an attachment or connect to a mailbox.
"""
import ipaddress
import os
import re
import unicodedata
from email.parser import Parser
from email.policy import default as default_policy
from email.utils import getaddresses, parseaddr
from urllib.parse import parse_qsl, urlsplit

COLLEGE_NAME = os.getenv("COLLEGE_NAME", "Ravenmoor College")
COLLEGE_DOMAIN = os.getenv("COLLEGE_DOMAIN", "ravenmoor.edu").lower()


class ToolError(Exception):
    """Bad tool input. The message is safe to show to the model and the user."""


# ---------------------------------------------------------------------------
# Domain helpers shared by both tools
# ---------------------------------------------------------------------------

# brand token -> domains that brand legitimately sends mail from / hosts pages on
OFFICIAL_DOMAINS: dict[str, set[str]] = {
    "microsoft": {"microsoft.com", "microsoftonline.com", "office.com", "office365.com",
                  "live.com", "outlook.com", "sharepoint.com", "onedrive.com"},
    "google": {"google.com", "gmail.com", "youtube.com", "googleusercontent.com"},
    "apple": {"apple.com", "icloud.com"},
    "paypal": {"paypal.com"},
    "amazon": {"amazon.com", "amazon.co.uk", "amazon.de"},
    "netflix": {"netflix.com"},
    "dhl": {"dhl.com"},
    "fedex": {"fedex.com"},
    "facebook": {"facebook.com", "facebookmail.com"},
    "instagram": {"instagram.com"},
    "linkedin": {"linkedin.com"},
    "dropbox": {"dropbox.com"},
    "docusign": {"docusign.com", "docusign.net"},
    COLLEGE_DOMAIN.split(".")[0]: {COLLEGE_DOMAIN},
}
# Product names that point to a brand above.
BRAND_ALIASES = {"outlook": "microsoft", "office365": "microsoft", "onedrive": "microsoft",
                 "sharepoint": "microsoft", "gmail": "google", "icloud": "apple"}
ALL_OFFICIAL = set().union(*OFFICIAL_DOMAINS.values())

MULTI_PART_SUFFIXES = {"co.uk", "ac.uk", "org.uk", "gov.uk", "co.il", "ac.il", "org.il",
                       "gov.il", "net.il", "com.au", "edu.au", "co.jp", "com.br", "co.in",
                       "co.za"}

FREE_MAIL = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com",
             "yahoo.com", "icloud.com", "aol.com", "proton.me", "protonmail.com",
             "gmx.com", "mail.com", "yandex.ru", "zoho.com"}

SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "ow.ly", "is.gd", "buff.ly",
              "cutt.ly", "rebrand.ly", "shorturl.at", "tiny.cc", "rb.gy"}

RISKY_TLDS = {"zip", "mov", "top", "xyz", "click", "country", "gq", "tk", "ml", "cf", "ga",
              "work", "support", "rest", "cam", "icu", "buzz", "monster"}

CREDENTIAL_WORDS = {"login", "signin", "sign-in", "logon", "verify", "verification", "account",
                    "password", "passwd", "update", "secure", "security", "sso", "auth",
                    "webmail", "mfa", "unlock", "suspend", "suspended", "billing"}

REDIRECT_PARAMS = {"url", "u", "redirect", "redirect_uri", "redirect_url", "next", "continue",
                   "dest", "destination", "target", "return", "returnurl", "goto", "link"}

# Characters that look like other characters, folded to one "skeleton" form.
CONFUSABLES = str.maketrans({
    "0": "o", "1": "l", "i": "l", "|": "l", "3": "e", "5": "s", "@": "a",
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "l",
    "ј": "j", "ѕ": "s", "ԁ": "d", "ɡ": "g", "ı": "l", "ο": "o", "α": "a", "ν": "v",
    "τ": "t", "ρ": "p", "κ": "k",
})


def registrable_domain(host: str) -> str:
    """Approximate 'organisational' domain: login.microsoft.com -> microsoft.com."""
    labels = [label for label in host.lower().rstrip(".").split(".") if label]
    if len(labels) >= 3 and ".".join(labels[-2:]) in MULTI_PART_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _skeleton(text: str) -> str:
    return text.lower().translate(CONFUSABLES).replace("rn", "m").replace("vv", "w")


def _levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _brand_for_token(token: str) -> str | None:
    token = token.lower()
    if token in OFFICIAL_DOMAINS:
        return token
    return BRAND_ALIASES.get(token)


def impersonated_brand(domain: str) -> dict | None:
    """If `domain` is not official but mentions or imitates a known brand, say which and how."""
    reg = registrable_domain(domain)
    if reg in ALL_OFFICIAL:
        return None

    host_part = domain.lower()[: -len(reg)].rstrip(".") if domain.lower().endswith(reg) else ""
    tokens = re.split(r"[.\-_]", domain.lower())
    for token in tokens:
        brand = _brand_for_token(token)
        if brand:
            where = "subdomain" if host_part and token in re.split(r"[.\-_]", host_part) else "domain"
            return {"brand": brand, "method": f"brand name in {where}",
                    "official_domains": sorted(OFFICIAL_DOMAINS[brand])}

    name = reg.split(".")[0]
    name_skel = _skeleton(name)
    for brand, official in OFFICIAL_DOMAINS.items():
        for off in official:
            off_name = off.split(".")[0]
            if name == off_name:
                return {"brand": brand, "method": "official name on a different domain ending",
                        "official_domains": sorted(official)}
            if len(off_name) < 4:
                continue
            if name_skel == _skeleton(off_name):
                return {"brand": brand, "method": "lookalike characters",
                        "official_domains": sorted(official)}
            limit = 1 if len(off_name) < 8 else 2
            if _levenshtein(name, off_name) <= limit:
                return {"brand": brand, "method": "near-identical spelling",
                        "official_domains": sorted(official)}
    return None


def _scripts(text: str) -> set[str]:
    return {unicodedata.name(ch, "UNKNOWN").split()[0] for ch in text if ch.isalpha()}


def _indicator(severity: str, code: str, detail: str) -> dict:
    return {"severity": severity, "code": code, "detail": detail}


def _assessment(indicators: list[dict]) -> str:
    severities = {i["severity"] for i in indicators}
    if "high" in severities:
        return "high_risk_indicators"
    if "medium" in severities:
        return "warning_signs"
    return "no_structural_red_flags"


# ---------------------------------------------------------------------------
# Tool 1: URL inspection
# ---------------------------------------------------------------------------

URL_LIMITATIONS = [
    "The link was analysed as text only. It was not opened, so the page content is unknown.",
    "HTTPS (the padlock) only means the connection is encrypted. Phishing sites use HTTPS too.",
    "A normal-looking address is not proof of safety: attackers also abuse real services "
    "(shared documents, form builders, compromised websites).",
]


def _refang(raw: str) -> tuple[str, bool]:
    fixed = (raw.replace("hxxps", "https").replace("hxxp", "http")
             .replace("[.]", ".").replace("(.)", ".").replace("[:]", ":").replace("[://]", "://"))
    return fixed, fixed != raw


def inspect_url(url: str) -> dict:
    if not isinstance(url, str) or not url.strip():
        raise ToolError("No URL was provided.")
    raw = url.strip().strip("<>\"' ")
    if len(raw) > 4000:
        raise ToolError("The URL is too long to analyse (over 4000 characters).")

    text, was_defanged = _refang(raw)
    indicators: list[dict] = []

    scheme_match = re.match(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):", text)
    if scheme_match and scheme_match.group(1).lower() in {"javascript", "data", "vbscript", "file"}:
        indicators.append(_indicator(
            "high", "dangerous_scheme",
            f"The link uses the '{scheme_match.group(1).lower()}:' scheme, which runs code or "
            "loads content directly instead of opening a website."))
        return {"input": raw, "scheme": scheme_match.group(1).lower(),
                "indicators": indicators, "assessment": "high_risk_indicators",
                "limitations": URL_LIMITATIONS}

    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", text):
        text = "http://" + text  # pasted without a scheme, e.g. "example.com/login"

    try:
        parts = urlsplit(text)
        hostname = parts.hostname or ""
        port = parts.port
    except ValueError as exc:
        raise ToolError(f"This does not look like a valid URL ({exc}).") from exc
    if not hostname:
        raise ToolError("Could not find a hostname in this URL.")

    # --- hostname as shown vs. its real (ASCII / punycode) form ---------------------
    hostname_unicode = hostname
    try:
        if any(label.startswith("xn--") for label in hostname.split(".")):
            hostname_unicode = hostname.encode("ascii").decode("idna")
        hostname_ascii = hostname_unicode.encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        hostname_ascii = hostname
    is_idn = hostname_unicode != hostname_ascii

    if parts.username is not None:
        user_text = parts.username + (f":{parts.password}" if parts.password else "")
        indicators.append(_indicator(
            "high", "userinfo_trick",
            f"Everything before the '@' ('{user_text}') is ignored by the browser. "
            f"The link really goes to '{hostname_unicode}'."))

    is_ip = False
    try:
        ipaddress.ip_address(hostname)
        is_ip = True
    except ValueError:
        if re.fullmatch(r"\d+|0x[0-9a-f]+", hostname):
            is_ip = True
    if is_ip:
        indicators.append(_indicator(
            "high", "ip_address_host",
            f"The link points to a raw IP address ({hostname}) instead of a domain name. "
            "Legitimate login pages almost never do this."))

    if is_idn:
        scripts = _scripts(hostname_unicode)
        detail = (f"The address contains non-Latin characters. It displays as "
                  f"'{hostname_unicode}' but the real domain is '{hostname_ascii}'.")
        if len(scripts) > 1:
            detail += f" It mixes alphabets ({', '.join(sorted(scripts))}), a common lookalike trick."
        indicators.append(_indicator("high", "internationalized_domain", detail))

    reg = registrable_domain(hostname_ascii) if not is_ip else hostname
    if not is_ip:
        brand = impersonated_brand(hostname_unicode) or impersonated_brand(hostname_ascii)
        if brand:
            indicators.append(_indicator(
                "high", "brand_impersonation",
                f"The address imitates {brand['brand'].title()} ({brand['method']}), but the real "
                f"domain is '{reg}', not one of {', '.join(brand['official_domains'])}."))

        if reg in SHORTENERS:
            indicators.append(_indicator(
                "medium", "url_shortener",
                f"'{reg}' is a link shortener. The final destination is hidden."))

        tld = reg.rsplit(".", 1)[-1]
        if tld in RISKY_TLDS:
            indicators.append(_indicator(
                "medium", "risky_tld",
                f"The domain ends in '.{tld}', an ending frequently used for throwaway or abusive sites."))

        if hostname_ascii.count(".") >= 4:
            indicators.append(_indicator(
                "low", "many_subdomains",
                f"The address has many parts ({hostname_ascii}). Long chains of subdomains are "
                "sometimes used to push the real domain out of view."))

    if parts.scheme == "http":
        indicators.append(_indicator(
            "low", "no_https", "The link is not encrypted (http, not https)."))

    if port and port not in (80, 443):
        indicators.append(_indicator(
            "low", "unusual_port", f"The link uses an unusual port ({port})."))

    path_and_query = f"{parts.path}?{parts.query}".lower()
    words = sorted(w for w in CREDENTIAL_WORDS if w in path_and_query)
    if words:
        indicators.append(_indicator(
            "low", "credential_keywords",
            f"The path contains account-related words ({', '.join(words)}), typical of login "
            "or 'verify your account' pages."))

    embedded = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in REDIRECT_PARAMS and re.match(r"^https?://", value, re.I):
            target_host = urlsplit(value).hostname or value
            embedded.append(target_host)
            indicators.append(_indicator(
                "medium", "embedded_redirect",
                f"The link carries another address in its '{key}' parameter, so it may forward "
                f"you on to '{target_host}'."))

    if len(text) > 200:
        indicators.append(_indicator(
            "low", "very_long", f"The link is unusually long ({len(text)} characters)."))

    return {
        "input": raw,
        "was_defanged": was_defanged,
        "scheme": parts.scheme,
        "hostname": hostname_unicode,
        "hostname_ascii": hostname_ascii,
        "registrable_domain": reg,
        "is_ip_address": is_ip,
        "port": port,
        "path": parts.path or "/",
        "embedded_redirect_hosts": embedded,
        "indicators": indicators,
        "assessment": _assessment(indicators),
        "limitations": URL_LIMITATIONS,
    }


# ---------------------------------------------------------------------------
# Tool 2: email-header inspection
# ---------------------------------------------------------------------------

HEADER_LIMITATIONS = [
    "Pasted headers can be edited, so these results are only as reliable as the copy provided.",
    "Authentication results are only trustworthy when added by your own mail provider "
    "(normally the top-most Authentication-Results header).",
    "Passing SPF, DKIM and DMARC only proves the message really came from the sender's domain. "
    "An attacker who registers a lookalike domain can pass all three.",
    "Headers say nothing about whether links or attachments in the message are safe.",
]


def _addr(value: str | None) -> dict | None:
    if not value:
        return None
    name, address = parseaddr(str(value))
    address = address.strip().lower()
    if not address and not name:
        return None
    domain = address.rsplit("@", 1)[1] if "@" in address else ""
    return {"display_name": name or None, "address": address or None,
            "domain": domain or None,
            "registrable_domain": registrable_domain(domain) if domain else None}


def _auth_results(header: str) -> dict:
    result = {"server": header.split(";", 1)[0].strip() or None}
    for method in ("spf", "dkim", "dmarc"):
        match = re.search(rf"\b{method}\s*=\s*([a-zA-Z]+)", header)
        result[method] = match.group(1).lower() if match else None
    for key in ("smtp.mailfrom", "header.from", "header.d", "header.i"):
        match = re.search(rf"\b{re.escape(key)}\s*=\s*([^\s;]+)", header)
        if match:
            result[key] = match.group(1).strip("<>").lower()
    return result


def inspect_email_headers(headers: str) -> dict:
    if not isinstance(headers, str) or not headers.strip():
        raise ToolError("No email headers were provided.")
    if len(headers) > 50000:
        raise ToolError("The headers are too long to analyse (over 50,000 characters).")

    text = "\n".join(line.rstrip() for line in headers.strip().replace("\r\n", "\n").split("\n"))
    msg = Parser(policy=default_policy).parsestr(text + "\n\n", headersonly=True)
    if not msg.keys():
        raise ToolError("No email headers were recognised. Paste the full header block "
                        "(lines like 'From:', 'Return-Path:', 'Authentication-Results:').")

    sender = _addr(msg.get("From"))
    reply_to = _addr(msg.get("Reply-To"))
    return_path = _addr(msg.get("Return-Path"))
    to = [a for _, a in getaddresses([str(v) for v in msg.get_all("To", [])]) if a]

    auth_headers = [str(h) for h in msg.get_all("Authentication-Results", [])]
    auth = _auth_results(auth_headers[0]) if auth_headers else None
    received_spf = msg.get("Received-SPF")
    spf_from_received = str(received_spf).split()[0].lower() if received_spf else None

    dkim_domains = []
    for sig in msg.get_all("DKIM-Signature", []):
        match = re.search(r"\bd\s*=\s*([^;\s]+)", str(sig))
        if match:
            dkim_domains.append(match.group(1).lower())

    received = [str(h) for h in msg.get_all("Received", [])]
    origin_ip = None
    if received:
        match = re.search(r"\[(\d{1,3}(?:\.\d{1,3}){3})\]", received[-1])
        origin_ip = match.group(1) if match else None

    indicators: list[dict] = []
    from_reg = sender["registrable_domain"] if sender else None

    if not sender or not sender["address"]:
        indicators.append(_indicator("medium", "no_from", "No usable 'From' address was found."))
    else:
        name = sender["display_name"] or ""
        embedded_addr = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", name)
        if embedded_addr and embedded_addr.group(0).lower() != sender["address"]:
            indicators.append(_indicator(
                "high", "display_name_spoof",
                f"The sender's name shows the address '{embedded_addr.group(0)}', but the "
                f"message really came from '{sender['address']}'."))

        name_tokens = re.split(r"[^a-z0-9]+", name.lower())
        for token in name_tokens:
            brand = _brand_for_token(token)
            if brand and from_reg not in OFFICIAL_DOMAINS[brand]:
                kind = "a free email account" if from_reg in FREE_MAIL else f"'{from_reg}'"
                indicators.append(_indicator(
                    "high", "display_name_brand_mismatch",
                    f"The sender's name mentions {brand.title()}, but the message was sent from "
                    f"{kind}, not an official {brand.title()} domain."))
                break

        brand = impersonated_brand(sender["domain"])
        if brand:
            indicators.append(_indicator(
                "high", "lookalike_sender_domain",
                f"The sender's domain '{sender['domain']}' imitates {brand['brand'].title()} "
                f"({brand['method']})."))

    if reply_to and reply_to["registrable_domain"] and from_reg \
            and reply_to["registrable_domain"] != from_reg:
        indicators.append(_indicator(
            "high", "reply_to_mismatch",
            f"Replies would go to '{reply_to['address']}', a different domain from the sender "
            f"('{from_reg}')."))

    if return_path and return_path["registrable_domain"] and from_reg \
            and return_path["registrable_domain"] != from_reg:
        indicators.append(_indicator(
            "medium", "return_path_mismatch",
            f"The bounce address (Return-Path) uses '{return_path['registrable_domain']}', not "
            f"'{from_reg}'. Mailing services do this legitimately, but it is also common in spoofing."))

    if auth:
        labels = {"spf": "SPF", "dkim": "DKIM", "dmarc": "DMARC"}
        for method, label in labels.items():
            outcome = auth.get(method)
            if outcome in {"fail", "permerror"}:
                indicators.append(_indicator(
                    "high", f"{method}_fail", f"{label} check failed ({outcome})."))
            elif outcome in {"softfail", "temperror", "neutral"}:
                indicators.append(_indicator(
                    "medium", f"{method}_weak", f"{label} result was '{outcome}', not a pass."))
            elif outcome in {None, "none"}:
                indicators.append(_indicator(
                    "medium", f"{method}_missing", f"No {label} result for this message."))
        if all(auth.get(m) == "pass" for m in labels):
            indicators.append(_indicator(
                "info", "authentication_passed",
                f"SPF, DKIM and DMARC all passed for '{from_reg}'. This confirms the sending domain, "
                "not that the sender is trustworthy."))
    elif spf_from_received:
        if spf_from_received in {"fail", "softfail"}:
            indicators.append(_indicator(
                "high" if spf_from_received == "fail" else "medium", "spf_fail",
                f"Received-SPF reports '{spf_from_received}'."))
    else:
        indicators.append(_indicator(
            "medium", "no_authentication_results",
            "The headers contain no authentication results, so the sender could not be verified."))

    if dkim_domains and from_reg and not any(registrable_domain(d) == from_reg for d in dkim_domains):
        indicators.append(_indicator(
            "medium", "dkim_not_aligned",
            f"The message was signed by '{', '.join(dkim_domains)}', not by the sender's domain "
            f"'{from_reg}'."))

    return {
        "from": sender,
        "reply_to": reply_to,
        "return_path": return_path,
        "to": to,
        "subject": str(msg.get("Subject")) if msg.get("Subject") else None,
        "date": str(msg.get("Date")) if msg.get("Date") else None,
        "authentication": auth,
        "received_spf": spf_from_received,
        "dkim_signing_domains": dkim_domains,
        "received_hops": len(received),
        "claimed_origin_ip": origin_ip,
        "indicators": indicators,
        "assessment": _assessment(indicators),
        "limitations": HEADER_LIMITATIONS,
    }


# ---------------------------------------------------------------------------
# Anthropic tool-use schemas and dispatcher
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = [
    {
        "name": "inspect_url",
        "description": (
            "Structurally analyse ONE URL that the user pasted, without visiting it. Reports the "
            "real hostname, '@' userinfo tricks, raw IP hosts, punycode/lookalike characters, "
            "brand impersonation, link shorteners, embedded redirects and similar warning signs. "
            "Use whenever the user shares a link or asks whether a link is safe. Call once per URL."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL exactly as the user provided it (defanged forms like "
                                   "hxxp://evil[.]com are accepted).",
                }
            },
            "required": ["url"],
        },
    },
    {
        "name": "inspect_email_headers",
        "description": (
            "Parse raw email headers the user pasted and check them for spoofing. Extracts From, "
            "Reply-To, Return-Path, SPF/DKIM/DMARC results and DKIM signing domains, and flags "
            "mismatches and lookalike sender domains. Use when the user pastes header lines "
            "(e.g. 'From:', 'Received:', 'Authentication-Results:'). Not for the email body."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "headers": {
                    "type": "string",
                    "description": "The raw header block exactly as pasted by the user.",
                }
            },
            "required": ["headers"],
        },
    },
]

_TOOL_FUNCTIONS = {
    "inspect_url": (inspect_url, "url"),
    "inspect_email_headers": (inspect_email_headers, "headers"),
}


def run_tool(name: str, tool_input: dict) -> dict:
    """Execute a tool by name. Raises ToolError for unknown tools or bad input."""
    if name not in _TOOL_FUNCTIONS:
        raise ToolError(f"Unknown tool '{name}'.")
    func, arg = _TOOL_FUNCTIONS[name]
    if not isinstance(tool_input, dict) or arg not in tool_input:
        raise ToolError(f"Tool '{name}' requires the '{arg}' field.")
    return func(tool_input[arg])
