"""Tests for the opt-in astroquery TAP CONNECT-proxy tunnel."""

from __future__ import annotations

import astroquery.utils.tap.conn.tapconn as tapconn

from src.crossref.tap_proxy import tap_proxy_tunnel


def test_noop_when_proxy_url_is_none() -> None:
    original = tapconn.httplib
    with tap_proxy_tunnel(None):
        assert tapconn.httplib is original  # unchanged
    assert tapconn.httplib is original


def test_noop_when_proxy_url_is_empty() -> None:
    original = tapconn.httplib
    with tap_proxy_tunnel(""):
        assert tapconn.httplib is original
    assert tapconn.httplib is original


def test_patches_and_restores_tapconn_httplib() -> None:
    original = tapconn.httplib
    with tap_proxy_tunnel("http://127.0.0.1:36389"):
        assert tapconn.httplib is not original
        assert hasattr(tapconn.httplib, "HTTPSConnection")
    assert tapconn.httplib is original  # restored on exit


def test_restores_even_on_exception() -> None:
    original = tapconn.httplib
    try:
        with tap_proxy_tunnel("http://127.0.0.1:36389"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert tapconn.httplib is original


def test_factory_builds_tunnelled_connection() -> None:
    with tap_proxy_tunnel("http://127.0.0.1:36389"):
        # Construct (but never connect) a connection; it should target the
        # proxy host/port and be set to tunnel to the real host.
        conn = tapconn.httplib.HTTPSConnection("gea.esac.esa.int", 443)
    assert conn.host == "127.0.0.1"
    assert conn.port == 36389
    assert conn._tunnel_host == "gea.esac.esa.int"
    assert conn._tunnel_port == 443
