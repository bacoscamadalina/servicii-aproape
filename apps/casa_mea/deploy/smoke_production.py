"""Read-only external smoke test for the deployed public HTTP boundary."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import ssl
import sys
from collections.abc import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def _strict_content_security_policy(value: str) -> bool:
    """Require the production directives without inline script/style exceptions."""

    required = (
        "default-src 'self'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "object-src 'none'",
        "script-src 'self'",
        "style-src 'self'",
        "upgrade-insecure-requests",
    )
    lowered = value.lower()
    return all(directive in lowered for directive in required) and all(
        exception not in lowered for exception in ("'unsafe-inline'", "'unsafe-eval'")
    )


SECURITY_HEADERS = {
    "strict-transport-security": lambda value: "max-age=" in value.lower(),
    "x-content-type-options": lambda value: value.lower() == "nosniff",
    "x-frame-options": lambda value: value.lower() == "deny",
    "referrer-policy": lambda value: bool(value.strip()),
    "cross-origin-opener-policy": lambda value: value.lower() == "same-origin",
    "content-security-policy": _strict_content_security_policy,
    "permissions-policy": lambda value: all(
        permission in value.replace(" ", "")
        for permission in ("camera=()", "geolocation=()", "microphone=()")
    ),
}


class ProductionSmokeError(RuntimeError):
    """Describe one failed external production invariant without response content."""


@dataclass(frozen=True)
class HttpProbe:
    """Bounded response projection used by the production smoke contract."""

    status: int
    headers: Mapping[str, str]
    set_cookies: tuple[str, ...]
    body: bytes


class _NoRedirect(HTTPRedirectHandler):
    """Return redirects to the smoke checker instead of following them silently."""

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def fetch_http_probe(url: str, *, timeout: float) -> HttpProbe:
    """Fetch one bounded response with normal TLS verification and no redirects."""

    request = Request(url, headers={"User-Agent": "ServiciiAproape-production-smoke/1"})
    opener = build_opener(_NoRedirect())
    try:
        try:
            response = opener.open(request, timeout=timeout)
        except HTTPError as exc:
            response = exc
        with response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ProductionSmokeError("A response exceeded the 2 MiB smoke limit.")
            return HttpProbe(
                status=response.status,
                headers={name.lower(): value for name, value in response.headers.items()},
                set_cookies=tuple(response.headers.get_all("Set-Cookie", ())),
                body=body,
            )
    except (URLError, TimeoutError, ssl.SSLError, OSError) as exc:
        raise ProductionSmokeError("The deployed origin could not be reached securely.") from exc


def _production_origin(base_url: str) -> str:
    """Require one canonical HTTPS origin, matching the production domain contract."""

    try:
        parsed = urlsplit(base_url)
        port = parsed.port
    except ValueError as exc:
        raise ProductionSmokeError("--base-url contains an invalid port.") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or port not in (None, 443)
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ProductionSmokeError(
            "--base-url must be one HTTPS origin without credentials, port, path, query or fragment."
        )
    return urlunsplit(("https", parsed.netloc, "/", "", ""))


def _require_security_headers(probe: HttpProbe, route: str) -> None:
    """Require the browser-facing headers configured by the production stack."""

    invalid = tuple(
        name
        for name, accepts in SECURITY_HEADERS.items()
        if not accepts(probe.headers.get(name, ""))
    )
    if invalid:
        raise ProductionSmokeError(
            f"{route} is missing or has invalid security headers: {', '.join(invalid)}."
        )


def run_production_smoke(
    *,
    base_url: str,
    timeout: float = 10,
    fetcher: Callable[..., HttpProbe] = fetch_http_probe,
) -> dict[str, object]:
    """Verify the external HTTP contract without authenticating or changing state."""

    origin = _production_origin(base_url)
    if not 0 < timeout <= 30:
        raise ProductionSmokeError("--timeout must be greater than 0 and at most 30 seconds.")

    http_origin = "http://" + urlsplit(origin).netloc + "/"
    redirect = fetcher(http_origin, timeout=timeout)
    if redirect.status not in (301, 308) or redirect.headers.get("location") != origin:
        raise ProductionSmokeError("Plain HTTP does not redirect exactly to the HTTPS origin.")

    routes = {
        "home_ro": ("", 200),
        "home_en": ("en/", 200),
        "admin_login": ("admin/login/", 200),
        "provider_dashboard": ("cont/profil/", 302),
        "private_media_probe": ("private_media/production-smoke-must-not-exist", 404),
    }
    probes: dict[str, HttpProbe] = {}
    for name, (path, expected_status) in routes.items():
        probe = fetcher(urljoin(origin, path), timeout=timeout)
        if probe.status != expected_status:
            raise ProductionSmokeError(
                f"{name} returned HTTP {probe.status}; expected {expected_status}."
            )
        _require_security_headers(probe, name)
        probes[name] = probe

    if b'<html lang="ro"' not in probes["home_ro"].body:
        raise ProductionSmokeError("The Romanian home page does not declare lang=ro.")
    if b'<html lang="en"' not in probes["home_en"].body:
        raise ProductionSmokeError("The English home page does not declare lang=en.")
    forbidden_preview_copy = (b"Copie de dezvoltare", b"Development copy")
    home_copy = probes["home_ro"].body + probes["home_en"].body
    if any(copy in home_copy for copy in forbidden_preview_copy):
        raise ProductionSmokeError("Development-preview copy is exposed by production.")

    dashboard_location = probes["provider_dashboard"].headers.get("location", "")
    login_path = urlsplit(dashboard_location).path
    if login_path not in ("/cont/autentificare/", "/en/cont/autentificare/"):
        raise ProductionSmokeError("The private provider dashboard does not redirect to login.")

    csrf_cookies = tuple(
        cookie
        for cookie in probes["admin_login"].set_cookies
        if cookie.lower().startswith("csrftoken=")
    )
    if len(csrf_cookies) != 1 or "secure" not in csrf_cookies[0].lower():
        raise ProductionSmokeError("The admin login does not issue exactly one Secure CSRF cookie.")

    return {
        "schema_version": 1,
        "valid": True,
        "checks": {
            "http_redirect": True,
            "https_security_headers": True,
            "romanian_home": True,
            "english_home": True,
            "admin_login": True,
            "provider_dashboard_private": True,
            "private_media_not_exposed": True,
            "secure_csrf_cookie": True,
            "development_copy_absent": True,
        },
    }


def main(argv: list[str] | None = None) -> int:
    """Print deterministic JSON for monitors and return non-zero on any violation."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--timeout", type=float, default=10)
    options = parser.parse_args(argv)
    try:
        report = run_production_smoke(
            base_url=options.base_url,
            timeout=options.timeout,
        )
    except ProductionSmokeError as exc:
        print(json.dumps({"schema_version": 1, "valid": False, "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
