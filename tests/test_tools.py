import pytest

from server.tools import (ToolError, impersonated_brand, inspect_email_headers, inspect_url,
                          registrable_domain, run_tool)


def codes(result):
    return {i["code"] for i in result["indicators"]}


# ---------------------------------------------------------------- helpers

@pytest.mark.parametrize("host, expected", [
    ("login.microsoft.com", "microsoft.com"),
    ("www.bbc.co.uk", "bbc.co.uk"),
    ("ravenmoor.edu", "ravenmoor.edu"),
])
def test_registrable_domain(host, expected):
    assert registrable_domain(host) == expected


def test_official_domains_are_not_impersonation():
    assert impersonated_brand("login.microsoftonline.com") is None
    assert impersonated_brand("mail.ravenmoor.edu") is None


# ---------------------------------------------------------------- inspect_url

def test_userinfo_trick():
    r = inspect_url("https://ravenmoor.edu@evil-site.ru/login")
    assert "userinfo_trick" in codes(r)
    assert r["registrable_domain"] == "evil-site.ru"
    assert r["assessment"] == "high_risk_indicators"


def test_ip_host():
    assert "ip_address_host" in codes(inspect_url("http://185.220.101.4/verify"))


def test_punycode_lookalike():
    r = inspect_url("https://xn--pple-43d.com/")  # 'аpple' with a Cyrillic 'а'
    assert "internationalized_domain" in codes(r)
    assert r["hostname"] != r["hostname_ascii"]


def test_brand_in_subdomain():
    r = inspect_url("https://microsoft.account-verify.xyz/signin")
    assert {"brand_impersonation", "risky_tld", "credential_keywords"} <= codes(r)


def test_typosquat():
    assert "brand_impersonation" in codes(inspect_url("https://paypa1.com/"))
    assert "brand_impersonation" in codes(inspect_url("https://ravenmor.edu/portal"))


def test_shortener_and_redirect():
    assert "url_shortener" in codes(inspect_url("https://bit.ly/3xYz"))
    r = inspect_url("https://www.google.com/url?q=x&url=https://evil.example/login")
    assert "embedded_redirect" in codes(r)
    assert r["embedded_redirect_hosts"] == ["evil.example"]


def test_defanged_and_schemeless():
    r = inspect_url("hxxps://evil[.]example/login")
    assert r["was_defanged"] and r["hostname"] == "evil.example"
    assert inspect_url("ravenmoor.edu/portal")["hostname"] == "ravenmoor.edu"


def test_legitimate_link_has_no_red_flags_but_keeps_limitations():
    r = inspect_url("https://portal.ravenmoor.edu/")
    assert r["assessment"] == "no_structural_red_flags"
    assert any("HTTPS" in note for note in r["limitations"])


def test_javascript_scheme():
    assert inspect_url("javascript:alert(1)")["assessment"] == "high_risk_indicators"


@pytest.mark.parametrize("bad", ["", "   ", "http://"])
def test_bad_url_input(bad):
    with pytest.raises(ToolError):
        inspect_url(bad)


# ---------------------------------------------------------------- inspect_email_headers

PHISH_HEADERS = """\
Return-Path: <bounce@mailer-xyz.top>
Authentication-Results: mx.ravenmoor.edu;
       spf=softfail smtp.mailfrom=mailer-xyz.top;
       dkim=none;
       dmarc=fail header.from=ravenmoor-support.com
From: "Ravenmoor IT Support" <it-desk@ravenmoor-support.com>
Reply-To: helpdesk.ravenmoor@gmail.com
To: student@ravenmoor.edu
Subject: Your account will be suspended today
Received: from mailer-xyz.top ([203.0.113.77]) by mx.ravenmoor.edu
"""

LEGIT_HEADERS = """\
Return-Path: <noreply@ravenmoor.edu>
Authentication-Results: mx.ravenmoor.edu;
       spf=pass smtp.mailfrom=ravenmoor.edu;
       dkim=pass header.d=ravenmoor.edu;
       dmarc=pass header.from=ravenmoor.edu
DKIM-Signature: v=1; a=rsa-sha256; d=ravenmoor.edu; s=sel1; h=from:to:subject; b=abc
From: Ravenmoor Library <noreply@ravenmoor.edu>
To: student@ravenmoor.edu
Subject: Your book is due tomorrow
"""


def test_phishing_headers():
    r = inspect_email_headers(PHISH_HEADERS)
    found = codes(r)
    assert {"reply_to_mismatch", "lookalike_sender_domain", "dmarc_fail",
            "spf_weak", "return_path_mismatch"} <= found
    assert r["from"]["address"] == "it-desk@ravenmoor-support.com"
    assert r["claimed_origin_ip"] == "203.0.113.77"
    assert r["assessment"] == "high_risk_indicators"


def test_legit_headers_pass_but_are_not_called_safe():
    r = inspect_email_headers(LEGIT_HEADERS)
    assert r["assessment"] == "no_structural_red_flags"
    assert "authentication_passed" in codes(r)
    assert any("lookalike" in note for note in r["limitations"])


def test_display_name_spoof():
    r = inspect_email_headers('From: "security@paypal.com" <alerts@pp-secure.net>\n')
    assert "display_name_spoof" in codes(r)


def test_no_headers():
    with pytest.raises(ToolError):
        inspect_email_headers("hello, is this email legit?")


# ---------------------------------------------------------------- dispatcher

def test_run_tool_validation():
    with pytest.raises(ToolError):
        run_tool("delete_everything", {})
    with pytest.raises(ToolError):
        run_tool("inspect_url", {"link": "x"})
    assert run_tool("inspect_url", {"url": "https://bit.ly/a"})["assessment"] == "warning_signs"
