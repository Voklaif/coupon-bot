import base64
import contextlib
import sqlite3
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from coupon_bot import db_init
from coupon_ui import build_handler
from http.server import ThreadingHTTPServer


USER = "admin"
PASS = "secret"


def _auth_header() -> str:
    token = base64.b64encode(f"{USER}:{PASS}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _seed_db(db_path: Path):
    db_init(str(db_path))
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO coupons (user_id, user_name, vendor, value_ils, code, cvv, barcode, expiry_utc, raw, created_utc, notified_expired)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                123,
                "Vlad",
                "TestStore",
                100,
                "ABC",
                "111",
                "999",
                "2099-01-01T00:00:00+00:00",
                "raw",
                "2026-03-06T00:00:00+00:00",
                0,
            ),
        )


def _start_server(db_path: Path):
    handler = build_handler(str(db_path), USER, PASS)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_health_no_auth(tmp_path: Path):
    db_path = tmp_path / "coupons.db"
    _seed_db(db_path)
    server, thread = _start_server(db_path)
    try:
        url = f"http://127.0.0.1:{server.server_port}/health"
        with urlopen(url, timeout=3) as resp:
            assert resp.status == 200
            assert resp.read().decode("utf-8") == "ok"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_dashboard_requires_auth(tmp_path: Path):
    db_path = tmp_path / "coupons.db"
    _seed_db(db_path)
    server, thread = _start_server(db_path)
    try:
        req = Request(f"http://127.0.0.1:{server.server_port}/")
        with pytest_raises_http_401():
            urlopen(req, timeout=3)
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_dashboard_and_delete_with_auth(tmp_path: Path):
    db_path = tmp_path / "coupons.db"
    _seed_db(db_path)
    server, thread = _start_server(db_path)
    try:
        req = Request(f"http://127.0.0.1:{server.server_port}/")
        req.add_header("Authorization", _auth_header())
        with urlopen(req, timeout=3) as resp:
            body = resp.read().decode("utf-8")
            assert resp.status == 200
            assert "TestStore" in body

        del_req = Request(f"http://127.0.0.1:{server.server_port}/actions/delete/1", method="POST")
        del_req.add_header("Authorization", _auth_header())
        with contextlib.suppress(HTTPError):
            urlopen(del_req, timeout=3)

        with sqlite3.connect(db_path) as conn:
            left = conn.execute("SELECT COUNT(*) FROM coupons").fetchone()[0]
            assert left == 0
    finally:
        server.shutdown()
        thread.join(timeout=2)


@contextlib.contextmanager
def pytest_raises_http_401():
    try:
        yield
        assert False, "Expected HTTPError 401"
    except HTTPError as exc:
        assert exc.code == 401
