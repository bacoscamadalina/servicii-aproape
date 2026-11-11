"""Production-only browser security headers for every Django response."""


CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "base-uri 'self'",
        "connect-src 'self'",
        "font-src 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "img-src 'self' data:",
        "object-src 'none'",
        "script-src 'self'",
        "style-src 'self'",
        "upgrade-insecure-requests",
    )
)
PERMISSIONS_POLICY = "camera=(), geolocation=(), microphone=()"


class ProductionBrowserSecurityMiddleware:
    """Attach the immutable production browser policy without inspecting content."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        response["Permissions-Policy"] = PERMISSIONS_POLICY
        return response
