"""Tests for the external, read-only production HTTP smoke contract."""

from pathlib import Path

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from deploy.smoke_production import HttpProbe, ProductionSmokeError, run_production_smoke
from services.middleware import (
    CONTENT_SECURITY_POLICY,
    PERMISSIONS_POLICY,
    ProductionBrowserSecurityMiddleware,
)


SECURITY_HEADERS = {
    "strict-transport-security": "max-age=31536000",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "same-origin",
    "cross-origin-opener-policy": "same-origin",
    "content-security-policy": CONTENT_SECURITY_POLICY,
    "permissions-policy": PERMISSIONS_POLICY,
}


class ProductionSmokeTests(SimpleTestCase):
    """Keep deployment checks strict, deterministic and independent of a live host."""

    @staticmethod
    def fetcher(url, *, timeout):
        del timeout
        if url.startswith("http://"):
            return HttpProbe(308, {"location": "https://example.ro/"}, (), b"")
        path = url.removeprefix("https://example.ro/")
        status = (
            302
            if path == "cont/profil/"
            else 404
            if path.startswith("private_media/")
            else 200
        )
        headers = {
            **SECURITY_HEADERS,
            **({"location": "/cont/autentificare/?next=/cont/profil/"} if status == 302 else {}),
        }
        cookies = (
            ("csrftoken=opaque; Path=/; SameSite=Lax; Secure",)
            if path == "admin/login/"
            else ()
        )
        body = b'<html lang="en">' if path == "en/" else b'<html lang="ro">'
        return HttpProbe(status, headers, cookies, body)

    def test_complete_public_boundary_passes(self):
        report = run_production_smoke(
            base_url="https://example.ro/", fetcher=self.fetcher
        )
        self.assertTrue(report["valid"])
        self.assertTrue(all(report["checks"].values()))

    def test_rejects_noncanonical_or_insecure_origins(self):
        for origin in (
            "http://example.ro/",
            "https://user@example.ro/",
            "https://example.ro:8443/",
            "https://example.ro:not-a-port/",
            "https://example.ro/app/",
            "https://example.ro/?debug=1",
        ):
            with self.subTest(origin=origin), self.assertRaises(ProductionSmokeError):
                run_production_smoke(base_url=origin, fetcher=self.fetcher)

    def test_rejects_missing_security_header(self):
        def fetcher(url, *, timeout):
            probe = self.fetcher(url, timeout=timeout)
            return HttpProbe(
                probe.status,
                {
                    name: value
                    for name, value in probe.headers.items()
                    if name != "x-frame-options"
                },
                probe.set_cookies,
                probe.body,
            )

        with self.assertRaisesRegex(ProductionSmokeError, "x-frame-options"):
            run_production_smoke(base_url="https://example.ro", fetcher=fetcher)

    def test_rejects_exposed_private_media_or_preview_copy(self):
        def exposed_media(url, *, timeout):
            probe = self.fetcher(url, timeout=timeout)
            return HttpProbe(
                200 if "private_media/" in url else probe.status,
                probe.headers,
                probe.set_cookies,
                probe.body,
            )

        with self.assertRaisesRegex(ProductionSmokeError, "private_media_probe"):
            run_production_smoke(base_url="https://example.ro", fetcher=exposed_media)

        def preview_copy(url, *, timeout):
            probe = self.fetcher(url, timeout=timeout)
            return HttpProbe(
                probe.status,
                probe.headers,
                probe.set_cookies,
                probe.body + (b"Development copy" if url.endswith("/en/") else b""),
            )

        with self.assertRaisesRegex(ProductionSmokeError, "Development-preview"):
            run_production_smoke(base_url="https://example.ro", fetcher=preview_copy)

    def test_rejects_dashboard_redirect_or_insecure_admin_cookie(self):
        def wrong_redirect(url, *, timeout):
            probe = self.fetcher(url, timeout=timeout)
            return HttpProbe(
                probe.status,
                {**probe.headers, **({"location": "/"} if "cont/profil" in url else {})},
                probe.set_cookies,
                probe.body,
            )

        with self.assertRaisesRegex(ProductionSmokeError, "does not redirect to login"):
            run_production_smoke(base_url="https://example.ro", fetcher=wrong_redirect)

        def insecure_cookie(url, *, timeout):
            probe = self.fetcher(url, timeout=timeout)
            cookies = (
                ("csrftoken=opaque; Path=/",)
                if "admin/login" in url
                else probe.set_cookies
            )
            return HttpProbe(probe.status, probe.headers, cookies, probe.body)

        with self.assertRaisesRegex(ProductionSmokeError, "Secure CSRF"):
            run_production_smoke(base_url="https://example.ro", fetcher=insecure_cookie)

    def test_production_middleware_sets_strict_browser_policy(self):
        request = RequestFactory().get("/", secure=True)
        response = ProductionBrowserSecurityMiddleware(
            lambda _request: HttpResponse("ok")
        )(request)

        self.assertEqual(response["Content-Security-Policy"], CONTENT_SECURITY_POLICY)
        self.assertEqual(response["Permissions-Policy"], PERMISSIONS_POLICY)
        self.assertNotIn("unsafe-inline", response["Content-Security-Policy"])
        self.assertNotIn("unsafe-eval", response["Content-Security-Policy"])

    def test_project_templates_contain_no_inline_styles_or_scripts(self):
        """Keep app-owned HTML compatible with the no-inline production CSP."""

        templates = Path(__file__).with_name("templates")
        for path in templates.rglob("*.html"):
            source = path.read_text(encoding="utf-8")
            with self.subTest(path=path):
                self.assertNotIn("<style", source.lower())
                self.assertNotIn(" style=", source.lower())
                for script in source.lower().split("<script")[1:]:
                    self.assertIn("src=", script.split(">", 1)[0])
