"""Optional CONNECT-proxy tunnelling for astroquery TAP clients.

astroquery's TAP layer (``astroquery.utils.tap.conn.tapconn``) opens raw
``http.client.HTTPSConnection`` sockets that ignore the ``HTTPS_PROXY``
environment variable. In environments where outbound HTTPS must traverse a
CONNECT proxy (sandboxes, some CI runners), that means Gaia TAP queries never
reach the server even when the host is otherwise allowlisted.

This module provides an opt-in context manager that, for its duration, routes
those TAP connections through a CONNECT proxy. It is a **no-op unless a proxy
URL is supplied**, so the default direct-network behaviour is unchanged.

Note: SIMBAD does not need this — ``astroquery.simbad`` issues its requests
through the ``requests`` library, which already honours ``HTTPS_PROXY``.
"""

from __future__ import annotations

import contextlib
import http.client
import ssl
import types
import urllib.parse
from collections.abc import Iterator


@contextlib.contextmanager
def tap_proxy_tunnel(
    proxy_url: str | None,
    ca_bundle: str | None = None,
) -> Iterator[None]:
    """Route astroquery TAP HTTPS connections through a CONNECT proxy.

    Args:
        proxy_url: CONNECT proxy URL (e.g. ``"http://127.0.0.1:36389"``). When
            falsy this is a no-op and astroquery connects directly.
        ca_bundle: Optional CA bundle path to trust for the (proxy-reterminated)
            TLS connection. Defaults to the standard system SSL context.

    Only astroquery's ``tapconn`` module reference is patched; the global
    ``http.client.HTTPSConnection`` is left untouched, and the original
    reference is always restored on exit.
    """
    if not proxy_url:
        yield
        return

    import astroquery.utils.tap.conn.tapconn as tapconn

    parsed = urllib.parse.urlparse(proxy_url)
    context = (
        ssl.create_default_context(cafile=ca_bundle) if ca_bundle else ssl.create_default_context()
    )
    original_https = http.client.HTTPSConnection

    def https_via_proxy(host, port=None, *args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.setdefault("context", context)
        conn = original_https(parsed.hostname, parsed.port, *args, **kwargs)
        conn.set_tunnel(host, port or 443)
        return conn

    original_httplib = tapconn.httplib
    tapconn.httplib = types.SimpleNamespace(
        HTTPSConnection=https_via_proxy,
        HTTPConnection=http.client.HTTPConnection,
    )
    try:
        yield
    finally:
        tapconn.httplib = original_httplib
