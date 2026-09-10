"""Authentication boundary for the loopback websockify listener.

Only nginx is expected to reach this listener.  nginx replaces any inbound
X-VibeStack-Proxy header with the fixed value supplied to this plugin by
Supervisor.  The marker is defense in depth for accidental/direct browser
access; it is deliberately not a user credential.
"""

from hmac import compare_digest

from websockify.auth_plugins import AuthenticationError


PROXY_HEADER = "X-VibeStack-Proxy"


class ProxyOnly:
    """Require exactly one nginx-injected proxy marker header."""

    def __init__(self, src):
        if not isinstance(src, str) or not src:
            raise ValueError("ProxyOnly requires a non-empty auth source")
        self._expected = src.encode("utf-8")

    def authenticate(self, headers, target_host, target_port):
        del target_host, target_port
        values = headers.get_all(PROXY_HEADER, [])
        single = len(values) == 1 and isinstance(values[0], str)
        candidate = values[0].encode("utf-8") if single else b""
        matches = compare_digest(candidate, self._expected)
        if not single or not matches:
            raise AuthenticationError(
                log_msg="missing or invalid reverse-proxy marker",
                response_code=403,
                response_msg="Forbidden",
            )
