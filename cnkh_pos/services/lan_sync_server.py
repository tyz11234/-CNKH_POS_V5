"""LAN-only sync HTTP + SSE/WebSocket API for CNKH POS (no cloud).

Bind 0.0.0.0:<port>. Optional shared secret via header ``X-CNKH-Token`` or
query ``token=``. Real-time: WebSocket ``/api/v1/ws`` and SSE ``/api/v1/events``,
plus lightweight poll. Pairing QR: ``cnkh-sync:v1|{json}``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import socket
import struct
import threading
import time
from collections import deque
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from cnkh_pos.database.connection import Database
from cnkh_pos.database.migrations import utc_now_text

DEFAULT_PORT = 8787
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
PAIRING_PREFIX = "cnkh-sync:v1|"


def detect_lan_ip() -> str:
    """Best-effort primary LAN IPv4 (not 127.0.0.1)."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.3)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            if info[0] == socket.AF_INET:
                ip = info[4][0]
                if ip and not ip.startswith("127."):
                    return ip
    except Exception:
        pass
    return "127.0.0.1"


def pairing_payload(
    *,
    base_url: str,
    token: str = "",
    name: str = "CNKH-PC",
    ttl_seconds: int = 420,
) -> str:
    """QR / clipboard payload for phone pairing (includes exp unix timestamp)."""
    import time as _time
    ttl = max(300, min(600, int(ttl_seconds or 420)))  # 5–10 min
    body = {
        "baseUrl": base_url.rstrip("/"),
        "token": token or "",
        "name": name or "CNKH-PC",
        "exp": int(_time.time()) + ttl,
    }
    return PAIRING_PREFIX + json.dumps(body, ensure_ascii=False, separators=(",", ":"))


class PairingExpiredError(ValueError):
    pass


def parse_pairing_payload(raw: str) -> dict[str, str] | None:
    """Return pairing dict or raise PairingExpiredError if exp passed."""
    import time as _time
    text = (raw or "").strip()
    data = None
    if text.startswith(PAIRING_PREFIX) or text.startswith("cnkh-sync:"):
        pipe = text.find("|")
        if pipe < 0:
            return None
        try:
            data = json.loads(text[pipe + 1 :])
        except json.JSONDecodeError:
            return None
    else:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict) or not data.get("baseUrl"):
        return None
    exp = data.get("exp")
    if exp is not None:
        try:
            if int(exp) < int(_time.time()):
                raise PairingExpiredError("pairing QR expired")
        except PairingExpiredError:
            raise
        except Exception:
            pass
    return {
        "baseUrl": str(data["baseUrl"]),
        "token": str(data.get("token") or ""),
        "name": str(data.get("name") or "CNKH-PC"),
        "exp": str(data.get("exp") or ""),
    }


class EventHub:
    """In-process pub/sub for SSE/WS clients and Qt listeners."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._seq = 0
        self._events: deque[dict[str, Any]] = deque(maxlen=500)
        self._listeners: list[Callable[[dict[str, Any]], None]] = []
        self._ws_clients: list[_WsClient] = []

    @property
    def seq(self) -> int:
        with self._lock:
            return self._seq

    def add_listener(self, cb: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            self._listeners.append(cb)

    def remove_listener(self, cb: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            if cb in self._listeners:
                self._listeners.remove(cb)

    def publish(self, event_type: str, **payload: Any) -> dict[str, Any]:
        with self._cond:
            self._seq += 1
            event = {
                "seq": self._seq,
                "type": event_type,
                "time": utc_now_text(),
                **payload,
            }
            self._events.append(event)
            listeners = list(self._listeners)
            clients = list(self._ws_clients)
            self._cond.notify_all()
        for cb in listeners:
            try:
                cb(event)
            except Exception:
                pass
        dead: list[_WsClient] = []
        for client in clients:
            try:
                client.send_json(event)
            except Exception:
                dead.append(client)
        if dead:
            with self._lock:
                for c in dead:
                    if c in self._ws_clients:
                        self._ws_clients.remove(c)
        return event

    def wait_after(self, last_seq: int, timeout: float = 25.0) -> list[dict[str, Any]]:
        deadline = time.time() + timeout
        with self._cond:
            while True:
                newer = [e for e in self._events if int(e["seq"]) > last_seq]
                if newer:
                    return newer
                remaining = deadline - time.time()
                if remaining <= 0:
                    return []
                self._cond.wait(timeout=remaining)

    def register_ws(self, client: _WsClient) -> None:
        with self._lock:
            self._ws_clients.append(client)

    def unregister_ws(self, client: _WsClient) -> None:
        with self._lock:
            if client in self._ws_clients:
                self._ws_clients.remove(client)


_HUB = EventHub()


def get_event_hub() -> EventHub:
    return _HUB


def publish_sync_event(event_type: str, **payload: Any) -> dict[str, Any]:
    """Publish from sale create paths (PC or after phone push)."""
    return _HUB.publish(event_type, **payload)


class _WsClient:
    def __init__(self, handler: BaseHTTPRequestHandler):
        self.handler = handler
        self._lock = threading.Lock()

    def send_json(self, obj: dict[str, Any]) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        header = bytearray([0x81])  # text, fin
        n = len(data)
        if n < 126:
            header.append(n)
        elif n < 65536:
            header.append(126)
            header.extend(struct.pack("!H", n))
        else:
            header.append(127)
            header.extend(struct.pack("!Q", n))
        with self._lock:
            self.handler.wfile.write(header + data)
            self.handler.wfile.flush()


class LanSyncServer:
    """Background ThreadingHTTPServer wrapper."""

    def __init__(
        self,
        database: Database,
        *,
        host: str = "0.0.0.0",
        port: int = DEFAULT_PORT,
        token: str = "",
        name: str = "CNKH-PC",
    ):
        self.database = database
        self.host = host
        self.port = int(port)
        self.token = (token or "").strip()
        self.name = name or "CNKH-PC"
        self.pair_ttl_seconds = 420
        self._pair_issued_at = 0.0
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._httpd is not None and self._thread is not None and self._thread.is_alive()

    @property
    def endpoint(self) -> str:
        return f"http://{detect_lan_ip()}:{self.port}"

    @property
    def pairing_qr_text(self) -> str:
        return pairing_payload(
            base_url=self.endpoint,
            token=self.token,
            name=self.name,
            ttl_seconds=self.pair_ttl_seconds,
        )

    def refresh_pairing_qr(self, *, ttl_seconds: int | None = None) -> str:
        if ttl_seconds is not None:
            self.pair_ttl_seconds = max(300, min(600, int(ttl_seconds)))
        import time as _time
        self._pair_issued_at = _time.time()
        return self.pairing_qr_text

    def start(self) -> str:
        with self._lock:
            if self.running:
                return self.endpoint
            handler = _make_handler(self.database, self.token, self)
            self._httpd = ThreadingHTTPServer((self.host, self.port), handler)
            self._thread = threading.Thread(
                target=self._httpd.serve_forever,
                name="cnkh-lan-sync",
                daemon=True,
            )
            self._thread.start()
            publish_sync_event("server_started", endpoint=self.endpoint)
            return self.endpoint

    def stop(self) -> None:
        with self._lock:
            if self._httpd is None:
                return
            try:
                self._httpd.shutdown()
            except Exception:
                pass
            try:
                self._httpd.server_close()
            except Exception:
                pass
            self._httpd = None
            self._thread = None
            publish_sync_event("server_stopped")


_ACTIVE: LanSyncServer | None = None
_ACTIVE_LOCK = threading.Lock()


def get_active_server() -> LanSyncServer | None:
    return _ACTIVE


def start_global_server(
    database: Database,
    *,
    port: int = DEFAULT_PORT,
    token: str = "",
    name: str = "CNKH-PC",
) -> LanSyncServer:
    global _ACTIVE
    with _ACTIVE_LOCK:
        if _ACTIVE is not None and _ACTIVE.running:
            _ACTIVE.stop()
        _ACTIVE = LanSyncServer(database, port=port, token=token, name=name)
        _ACTIVE.start()
        return _ACTIVE


def stop_global_server() -> None:
    global _ACTIVE
    with _ACTIVE_LOCK:
        if _ACTIVE is not None:
            _ACTIVE.stop()
            _ACTIVE = None


def _make_handler(database: Database, expected_token: str, server: LanSyncServer):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            return

        def _auth_ok(self) -> bool:
            if not expected_token:
                return True
            hdr = self.headers.get("X-CNKH-Token", "")
            qs = parse_qs(urlparse(self.path).query)
            q = (qs.get("token") or [""])[0]
            return hdr == expected_token or q == expected_token

        def _send(self, code: int, payload: Any) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header(
                "Access-Control-Allow-Headers", "Content-Type, X-CNKH-Token"
            )
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header(
                "Access-Control-Allow-Headers", "Content-Type, X-CNKH-Token"
            )
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            qs = parse_qs(parsed.query)
            since = (qs.get("since") or [""])[0].strip()

            if path in {"/health", "/api/v1/health"}:
                self._send(
                    200,
                    {
                        "ok": True,
                        "service": "cnkh-lan-sync",
                        "time": utc_now_text(),
                        "auth_required": bool(expected_token),
                        "ws": "/api/v1/ws",
                        "sse": "/api/v1/events",
                        "pairing": server.pairing_qr_text,
                    },
                )
                return

            # WebSocket upgrade
            if path == "/api/v1/ws":
                if not self._auth_ok():
                    self._send(401, {"ok": False, "error": "unauthorized"})
                    return
                if (self.headers.get("Upgrade") or "").lower() != "websocket":
                    self._send(400, {"ok": False, "error": "expected websocket upgrade"})
                    return
                self._websocket_loop()
                return

            if path == "/api/v1/events":
                if not self._auth_ok():
                    self._send(401, {"ok": False, "error": "unauthorized"})
                    return
                self._sse_loop(int((qs.get("after") or ["0"])[0] or 0))
                return

            if path == "/api/v1/events/poll":
                if not self._auth_ok():
                    self._send(401, {"ok": False, "error": "unauthorized"})
                    return
                after = int((qs.get("after") or ["0"])[0] or 0)
                events = _HUB.wait_after(after, timeout=0.05)
                # non-blocking snapshot
                with _HUB._lock:
                    events = [e for e in _HUB._events if int(e["seq"]) > after]
                self._send(
                    200, {"ok": True, "events": events, "seq": _HUB.seq}
                )
                return

            if not self._auth_ok():
                self._send(401, {"ok": False, "error": "unauthorized"})
                return
            if path == "/api/v1/products":
                self._send(200, {"ok": True, "items": _pull_products(database, since)})
                return
            if path == "/api/v1/customers":
                self._send(200, {"ok": True, "items": _pull_customers(database, since)})
                return
            if path == "/api/v1/sales":
                self._send(200, {"ok": True, "items": _pull_sales(database, since)})
                return
            if path == "/api/v1/categories":
                self._send(200, {"ok": True, "items": _pull_categories(database, since)})
                return
            if path.startswith("/api/v1/product_images/"):
                pid_s = path.rsplit("/", 1)[-1]
                try:
                    pid = int(pid_s)
                except ValueError:
                    self._send(400, {"ok": False, "error": "bad product id"})
                    return
                img = _product_image_path(database, pid)
                if not img.exists():
                    self._send(404, {"ok": False, "error": "no image"})
                    return
                data = img.read_bytes()
                b64 = base64.b64encode(data).decode("ascii")
                self._send(
                    200,
                    {
                        "ok": True,
                        "product_id": pid,
                        "ext": img.suffix.lstrip(".") or "jpg",
                        "base64": b64,
                        "size": len(data),
                    },
                )
                return
            if path == "/api/v1/barcode_queue":
                self._send(200, {"ok": True, "items": _pull_barcode_queue(database)})
                return
            if path == "/api/v1/pairing":
                self._send(
                    200,
                    {
                        "ok": True,
                        "payload": server.pairing_qr_text,
                        "endpoint": server.endpoint,
                    },
                )
                return
            self._send(404, {"ok": False, "error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            if not self._auth_ok():
                self._send(401, {"ok": False, "error": "unauthorized"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                self._send(400, {"ok": False, "error": "invalid json"})
                return
            if path == "/api/v1/sales":
                result = _push_sales(database, payload)
                if result.get("ok") and int(result.get("imported") or 0) > 0:
                    publish_sync_event(
                        "sale",
                        source="phone",
                        imported=result.get("imported"),
                        receipt_nos=[
                            s.get("receipt_no")
                            for s in (payload.get("sales") or [])
                            if isinstance(s, dict)
                        ],
                    )
                    try:
                        publish_low_stock_events(database)
                    except Exception:
                        pass
                self._send(200 if result.get("ok") else 400, result)
                return
            if path == "/api/v1/notify":
                # PC (or phone) announces a local change
                et = str(payload.get("type") or "sale")
                event = publish_sync_event(et, source=payload.get("source") or "pc", **{
                    k: v
                    for k, v in payload.items()
                    if k not in {"type", "source"}
                })
                self._send(200, {"ok": True, "event": event})
                return
            if path.startswith("/api/v1/product_images/"):
                pid_s = path.rsplit("/", 1)[-1]
                try:
                    pid = int(pid_s)
                except ValueError:
                    self._send(400, {"ok": False, "error": "bad product id"})
                    return
                b64 = str(payload.get("base64") or "")
                if not b64:
                    self._send(400, {"ok": False, "error": "base64 required"})
                    return
                try:
                    raw_img = base64.b64decode(b64)
                except Exception:
                    self._send(400, {"ok": False, "error": "invalid base64"})
                    return
                if len(raw_img) > 2_500_000:
                    self._send(400, {"ok": False, "error": "image too large"})
                    return
                ext = str(payload.get("ext") or "jpg").lstrip(".").lower() or "jpg"
                if ext not in {"jpg", "jpeg", "png", "webp"}:
                    ext = "jpg"
                dest = _product_images_dir(database) / f"{pid}.{ext}"
                # remove other extensions
                for oldp in _product_images_dir(database).glob(f"{pid}.*"):
                    try:
                        oldp.unlink()
                    except Exception:
                        pass
                dest.write_bytes(raw_img)
                publish_sync_event("product_image", source="phone", product_id=pid)
                self._send(200, {"ok": True, "product_id": pid, "size": len(raw_img)})
                return
            if path == "/api/v1/categories":
                # optional phone→PC category upsert by name
                items = payload.get("items") or payload.get("categories") or []
                saved = 0
                with database.transaction() as conn:
                    for it in items:
                        if not isinstance(it, dict):
                            continue
                        name = str(it.get("name") or "").strip()
                        if not name:
                            continue
                        now = utc_now_text()
                        row = conn.execute(
                            "SELECT id FROM categories WHERE name=? COLLATE NOCASE",
                            (name,),
                        ).fetchone()
                        if row is None:
                            conn.execute(
                                "INSERT INTO categories(name, created_at, updated_at) VALUES (?,?,?)",
                                (name, now, now),
                            )
                        else:
                            conn.execute(
                                "UPDATE categories SET updated_at=?, is_deleted=0 WHERE id=?",
                                (now, int(row["id"])),
                            )
                        saved += 1
                publish_sync_event("category", source="phone", saved=saved)
                self._send(200, {"ok": True, "saved": saved})
                return
            if path == "/api/v1/barcode_queue":
                items = payload.get("items") or payload.get("queue") or []
                saved = _push_barcode_queue(database, items if isinstance(items, list) else [])
                publish_sync_event("barcode_queue", source="phone", saved=saved)
                self._send(200, {"ok": True, "saved": saved})
                return
            self._send(404, {"ok": False, "error": "not found"})

        def _sse_loop(self, after: int) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            last = after
            try:
                while True:
                    events = _HUB.wait_after(last, timeout=20.0)
                    if not events:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        continue
                    for event in events:
                        last = int(event["seq"])
                        data = json.dumps(event, ensure_ascii=False)
                        self.wfile.write(f"data: {data}\n\n".encode())
                    self.wfile.flush()
            except Exception:
                return

        def _websocket_loop(self) -> None:
            key = self.headers.get("Sec-WebSocket-Key", "")
            accept = base64.b64encode(
                hashlib.sha1((key + WS_GUID).encode("utf-8")).digest()
            ).decode("ascii")
            self.send_response(101, "Switching Protocols")
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.end_headers()
            client = _WsClient(self)
            _HUB.register_ws(client)
            try:
                client.send_json(
                    {"type": "hello", "seq": _HUB.seq, "time": utc_now_text()}
                )
                # Read loop — keep connection until client disconnects
                while True:
                    hdr = self.rfile.read(2)
                    if not hdr or len(hdr) < 2:
                        break
                    b1, b2 = hdr[0], hdr[1]
                    opcode = b1 & 0x0F
                    masked = (b2 & 0x80) != 0
                    length = b2 & 0x7F
                    if length == 126:
                        length = struct.unpack("!H", self.rfile.read(2))[0]
                    elif length == 127:
                        length = struct.unpack("!Q", self.rfile.read(8))[0]
                    mask = self.rfile.read(4) if masked else b""
                    payload = self.rfile.read(length) if length else b""
                    if masked and payload:
                        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
                    if opcode == 0x8:  # close
                        break
                    if opcode == 0x9:  # ping -> pong
                        frame = bytearray([0x8A, len(payload)]) + payload
                        self.wfile.write(frame)
                        self.wfile.flush()
                    elif opcode == 0x1 and payload:
                        try:
                            msg = json.loads(payload.decode("utf-8"))
                        except json.JSONDecodeError:
                            continue
                        if isinstance(msg, dict) and msg.get("type") == "ping":
                            client.send_json({"type": "pong", "time": utc_now_text()})
            except Exception:
                pass
            finally:
                _HUB.unregister_ws(client)

    return Handler




def _barcode_queue_path(database: Database):
    from pathlib import Path
    return Path(database.path).resolve().parent / "barcode_print_queue.json"


def _pull_barcode_queue(database: Database) -> list[dict[str, Any]]:
    path = _barcode_queue_path(database)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _push_barcode_queue(database: Database, items: list[Any]) -> int:
    path = _barcode_queue_path(database)
    existing = _pull_barcode_queue(database)
    seen = {(str(x.get("barcode")), str(x.get("product_name"))) for x in existing if isinstance(x, dict)}
    saved = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        key = (str(it.get("barcode") or ""), str(it.get("product_name") or ""))
        if not key[0]:
            continue
        if key in seen:
            continue
        existing.append(
            {
                "barcode": key[0],
                "product_name": key[1],
                "sku": str(it.get("sku") or ""),
                "price_cents": int(it.get("price_cents") or 0),
                "copies": max(1, int(it.get("copies") or 1)),
                "product_id": str(it.get("product_id") or ""),
                "source": str(it.get("source") or "phone"),
                "created_at": str(it.get("created_at") or utc_now_text()),
                "status": "pending",
            }
        )
        seen.add(key)
        saved += 1
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    return saved


def _product_images_dir(database: Database):
    from pathlib import Path
    root = Path(database.path).resolve().parent / "product_images"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _product_image_path(database: Database, product_id: int):
    d = _product_images_dir(database)
    for ext in ("jpg", "jpeg", "png", "webp"):
        p = d / f"{product_id}.{ext}"
        if p.exists():
            return p
    return d / f"{product_id}.jpg"


def _pull_categories(database: Database, since: str = "") -> list[dict[str, Any]]:
    conn = database.connect(readonly=True)
    try:
        if since:
            rows = conn.execute(
                """SELECT id,name,is_deleted,updated_at FROM categories
                   WHERE updated_at > ? ORDER BY updated_at,id""",
                (since,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id,name,is_deleted,updated_at FROM categories
                   ORDER BY name COLLATE NOCASE"""
            ).fetchall()
        return [
            {
                "pc_id": int(r["id"]),
                "name": r["name"],
                "is_deleted": int(r["is_deleted"] or 0),
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]
    finally:
        conn.close()


def publish_low_stock_events(database: Database, product_ids: list[int] | None = None) -> list[dict[str, Any]]:
    """Publish low_stock events for products at/below reorder or default threshold."""
    conn = database.connect(readonly=True)
    events: list[dict[str, Any]] = []
    try:
        default_thr = 10.0
        try:
            import json as _json
            row = conn.execute(
                "SELECT value_json FROM settings WHERE key='low_stock_threshold'"
            ).fetchone()
            if row and row["value_json"]:
                raw = row["value_json"]
                try:
                    raw = _json.loads(raw)
                except Exception:
                    pass
                default_thr = float(raw)
        except Exception:
            pass
        if product_ids:
            placeholders = ",".join("?" for _ in product_ids)
            rows = conn.execute(
                f"""SELECT id,name,sku,barcode,stock_decimal,low_stock_decimal
                    FROM products WHERE is_deleted=0 AND id IN ({placeholders})""",
                tuple(product_ids),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id,name,sku,barcode,stock_decimal,low_stock_decimal
                   FROM products WHERE is_deleted=0"""
            ).fetchall()
        for r in rows:
            stock = float(r["stock_decimal"] or 0)
            reorder = float(r["low_stock_decimal"] or 0)
            thr = reorder if reorder > 0 else default_thr
            if stock <= thr:
                ev = publish_sync_event(
                    "low_stock",
                    source="pc",
                    product_id=int(r["id"]),
                    name=r["name"],
                    sku=r["sku"] or "",
                    barcode=r["barcode"] or "",
                    stock=stock,
                    threshold=thr,
                )
                events.append(ev)
    finally:
        conn.close()
    return events


def _pull_products(database: Database, since: str) -> list[dict[str, Any]]:
    conn = database.connect(readonly=True)
    try:
        sql = """SELECT p.id,p.name,p.sku,p.barcode,p.cost_cents,p.selling_price_cents,
                        p.stock_decimal,p.unit,p.location,p.low_stock_decimal,
                        p.category_id, COALESCE(c.name,'') AS category_name,
                        p.is_deleted,p.updated_at
                 FROM products p
                 LEFT JOIN categories c ON c.id = p.category_id"""
        if since:
            rows = conn.execute(
                sql + " WHERE p.updated_at > ? ORDER BY p.updated_at,p.id",
                (since,),
            ).fetchall()
        else:
            rows = conn.execute(sql + " ORDER BY p.updated_at,p.id").fetchall()
        out = []
        for r in rows:
            cat = (r["category_name"] or "").strip() or (r["location"] or "")
            out.append(
                {
                    "pc_id": int(r["id"]),
                    "name": r["name"],
                    "name_zh": r["name"],
                    "name_en": r["name"],
                    "sku": r["sku"] or "",
                    "barcode": r["barcode"] or "",
                    "cost_cents": int(r["cost_cents"] or 0),
                    "price_cents": int(r["selling_price_cents"] or 0),
                    "stock": float(r["stock_decimal"] or 0),
                    "unit": r["unit"] or "pcs",
                    "category": cat,
                    "reorder_level": float(r["low_stock_decimal"] or 0),
                    "has_image": _product_image_path(database, int(r["id"])).exists(),
                    "is_deleted": int(r["is_deleted"] or 0),
                    "updated_at": r["updated_at"],
                }
            )
        return out
    finally:
        conn.close()


def _pull_customers(database: Database, since: str) -> list[dict[str, Any]]:
    conn = database.connect(readonly=True)
    try:
        if since:
            rows = conn.execute(
                """SELECT id,name,phone,notes,is_deleted,updated_at
                   FROM customers WHERE updated_at > ? ORDER BY updated_at,id""",
                (since,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id,name,phone,notes,is_deleted,updated_at
                   FROM customers ORDER BY updated_at,id"""
            ).fetchall()
        return [
            {
                "pc_id": int(r["id"]),
                "name": r["name"],
                "phone": r["phone"] or "",
                "notes": r["notes"] or "",
                "is_deleted": int(r["is_deleted"] or 0),
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]
    finally:
        conn.close()


def _pull_sales(database: Database, since: str) -> list[dict[str, Any]]:
    conn = database.connect(readonly=True)
    try:
        if since:
            rows = conn.execute(
                """SELECT id,receipt_no,sold_at,total_cents,paid_cents,change_cents,
                          payment_method,deposit_method,customer_id,subtotal_cents,
                          discount_cents,is_deleted
                   FROM sales WHERE sold_at > ? ORDER BY sold_at,id""",
                (since,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id,receipt_no,sold_at,total_cents,paid_cents,change_cents,
                          payment_method,deposit_method,customer_id,subtotal_cents,
                          discount_cents,is_deleted
                   FROM sales ORDER BY sold_at DESC LIMIT 500"""
            ).fetchall()
        items = []
        for r in rows:
            lines = conn.execute(
                """SELECT product_name_snapshot,sku_snapshot,barcode_snapshot,
                          quantity_decimal,unit_price_cents,discount_cents,subtotal_cents
                   FROM sale_items WHERE sale_id=?""",
                (r["id"],),
            ).fetchall()
            cust_phone = ""
            cust_name = ""
            if r["customer_id"]:
                c = conn.execute(
                    "SELECT name,phone FROM customers WHERE id=?",
                    (r["customer_id"],),
                ).fetchone()
                if c:
                    cust_name = c["name"] or ""
                    cust_phone = c["phone"] or ""
            items.append(
                {
                    "pc_id": int(r["id"]),
                    "receipt_no": r["receipt_no"],
                    "sold_at": r["sold_at"],
                    "total_cents": int(r["total_cents"]),
                    "paid_cents": int(r["paid_cents"]),
                    "change_cents": int(r["change_cents"]),
                    "payment_method": r["payment_method"],
                    "deposit_method": r["deposit_method"],
                    "customer_name": cust_name,
                    "customer_phone": cust_phone,
                    "subtotal_cents": int(r["subtotal_cents"]),
                    "discount_cents": int(r["discount_cents"]),
                    "is_deleted": int(r["is_deleted"] or 0),
                    "lines": [
                        {
                            "nameZh": ln["product_name_snapshot"],
                            "sku": ln["sku_snapshot"] or "",
                            "barcode": ln["barcode_snapshot"] or "",
                            "qty": float(ln["quantity_decimal"] or 0),
                            "unitPriceCents": int(ln["unit_price_cents"] or 0),
                            "lineDiscountCents": int(ln["discount_cents"] or 0),
                            "lineTotalCents": int(ln["subtotal_cents"] or 0),
                        }
                        for ln in lines
                    ],
                }
            )
        return items
    finally:
        conn.close()


def _push_sales(database: Database, payload: dict[str, Any]) -> dict[str, Any]:
    """Accept phone-originated sales; skip duplicates by receipt_no."""
    sales = payload.get("sales") or payload.get("items") or []
    if not isinstance(sales, list):
        return {"ok": False, "error": "sales must be a list"}
    imported = 0
    skipped = 0
    errors: list[str] = []
    with database.transaction() as conn:
        for sale in sales:
            try:
                receipt_no = str(sale.get("receipt_no") or "").strip()
                if not receipt_no:
                    errors.append("missing receipt_no")
                    continue
                exists = conn.execute(
                    "SELECT id FROM sales WHERE receipt_no=?", (receipt_no,)
                ).fetchone()
                if exists:
                    skipped += 1
                    continue
                customer_id = None
                phone = str(sale.get("customer_phone") or "").strip()
                cname = str(sale.get("customer_name") or "").strip()
                if phone or cname:
                    row = None
                    if phone:
                        row = conn.execute(
                            "SELECT id FROM customers WHERE phone=? AND is_deleted=0",
                            (phone,),
                        ).fetchone()
                    if row is None and cname:
                        row = conn.execute(
                            "SELECT id FROM customers WHERE name=? AND is_deleted=0",
                            (cname,),
                        ).fetchone()
                    if row is None:
                        now = utc_now_text()
                        cur = conn.execute(
                            """INSERT INTO customers(name,phone,notes,is_deleted,created_at,updated_at)
                               VALUES (?,?, '',0,?,?)""",
                            (cname or phone or "Mobile", phone, now, now),
                        )
                        customer_id = int(cur.lastrowid)
                    else:
                        customer_id = int(row["id"])
                method = str(sale.get("payment_method") or "CASH").upper()
                if method not in {"CASH", "CARD", "DUITNOW_QR", "CREDIT"}:
                    method = "CASH"
                deposit = sale.get("deposit_method")
                if deposit:
                    deposit = str(deposit).upper()
                    if deposit not in {"CASH", "CARD", "DUITNOW_QR"}:
                        deposit = None
                total = int(sale.get("total_cents") or 0)
                paid = int(sale.get("paid_cents") or total)
                change = int(sale.get("change_cents") or max(0, paid - total))
                subtotal = int(sale.get("subtotal_cents") or total)
                discount = int(
                    sale.get("discount_cents") or sale.get("order_discount_cents") or 0
                )
                sold_at = str(sale.get("sold_at") or utc_now_text())
                cur = conn.execute(
                    """INSERT INTO sales(
                        receipt_no,subtotal_cents,discount_cents,total_cents,paid_cents,
                        change_cents,payment_method,deposit_method,customer_id,cashier_id,
                        sold_at,is_deleted
                    ) VALUES (?,?,?,?,?,?,?,?,?,NULL,?,0)""",
                    (
                        receipt_no,
                        subtotal,
                        discount,
                        total,
                        paid,
                        change,
                        method,
                        deposit,
                        customer_id,
                        sold_at,
                    ),
                )
                sale_id = int(cur.lastrowid)
                for ln in sale.get("lines") or []:
                    name = str(ln.get("nameZh") or ln.get("name") or "Item")
                    sku = str(ln.get("sku") or "")
                    barcode = str(ln.get("barcode") or "")
                    qty = str(ln.get("qty") or ln.get("quantity") or "1")
                    unit = int(ln.get("unitPriceCents") or ln.get("unit_price_cents") or 0)
                    disc = int(ln.get("lineDiscountCents") or ln.get("discount_cents") or 0)
                    sub = int(ln.get("lineTotalCents") or ln.get("subtotal_cents") or unit)
                    product_id = None
                    if barcode:
                        pr = conn.execute(
                            "SELECT id FROM products WHERE barcode=? AND is_deleted=0",
                            (barcode,),
                        ).fetchone()
                        if pr:
                            product_id = int(pr["id"])
                    if product_id is None and sku:
                        pr = conn.execute(
                            "SELECT id FROM products WHERE sku=? AND is_deleted=0",
                            (sku,),
                        ).fetchone()
                        if pr:
                            product_id = int(pr["id"])
                    conn.execute(
                        """INSERT INTO sale_items(
                            sale_id,product_id,product_name_snapshot,sku_snapshot,
                            barcode_snapshot,unit_snapshot,quantity_decimal,
                            stock_deduction_decimal,unit_price_cents,
                            discount_cents,subtotal_cents,returned_stock_decimal
                        ) VALUES (?,?,?,?,?,'pcs',?,?,?,?,?,'0')""",
                        (
                            sale_id,
                            product_id,
                            name,
                            sku,
                            barcode,
                            qty,
                            qty,
                            unit,
                            disc,
                            sub,
                        ),
                    )
                    if product_id is not None:
                        try:
                            conn.execute(
                                """UPDATE products SET stock_decimal =
                                   printf('%.4f', CAST(stock_decimal AS REAL) - CAST(? AS REAL)),
                                   updated_at=? WHERE id=?""",
                                (qty, utc_now_text(), product_id),
                            )
                        except Exception:
                            pass
                imported += 1
            except Exception as exc:
                errors.append(str(exc))
    return {
        "ok": True,
        "imported": imported,
        "skipped": skipped,
        "errors": errors[:20],
        "time": utc_now_text(),
    }
