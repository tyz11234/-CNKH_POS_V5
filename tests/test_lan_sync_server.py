import json
import urllib.error
import urllib.request

from cnkh_pos.database.bootstrap import bootstrap_database
from cnkh_pos.database.connection import Database
from cnkh_pos.services.lan_sync_server import LanSyncServer


def _get(url, token=""):
    req = urllib.request.Request(url)
    if token:
        req.add_header("X-CNKH-Token", token)
    with urllib.request.urlopen(req, timeout=3) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post(url, payload, token=""):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST", headers={"Content-Type": "application/json"}
    )
    if token:
        req.add_header("X-CNKH-Token", token)
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def test_lan_sync_health_and_auth(tmp_path):
    db_path = tmp_path / "hardware_pos.db"
    backup = tmp_path / "backups"
    bootstrap_database(db_path, backup)
    database = Database(db_path)
    srv = LanSyncServer(database, host="127.0.0.1", port=18787, token="secret")
    endpoint = srv.start()
    try:
        assert "18787" in endpoint
        health = _get("http://127.0.0.1:18787/api/v1/health")
        assert health["ok"] is True
        try:
            _get("http://127.0.0.1:18787/api/v1/products")
            raised = False
        except urllib.error.HTTPError as exc:
            raised = exc.code == 401
        assert raised
        products = _get("http://127.0.0.1:18787/api/v1/products", token="secret")
        assert products["ok"] is True
        assert isinstance(products["items"], list)
        pushed = _post(
            "http://127.0.0.1:18787/api/v1/sales",
            {
                "sales": [
                    {
                        "receipt_no": "MTEST-0001",
                        "sold_at": "2026-09-04T12:00:00",
                        "payment_method": "CASH",
                        "total_cents": 100,
                        "paid_cents": 100,
                        "change_cents": 0,
                        "subtotal_cents": 100,
                        "discount_cents": 0,
                        "customer_name": "Test",
                        "customer_phone": "0123456789",
                        "lines": [
                            {
                                "nameZh": "Item",
                                "qty": 1,
                                "unitPriceCents": 100,
                                "lineTotalCents": 100,
                            }
                        ],
                    }
                ]
            },
            token="secret",
        )
        assert pushed["ok"] is True
        assert pushed["imported"] == 1
        again = _post(
            "http://127.0.0.1:18787/api/v1/sales",
            {
                "sales": [
                    {
                        "receipt_no": "MTEST-0001",
                        "sold_at": "2026-09-04T12:00:00",
                        "payment_method": "CASH",
                        "total_cents": 100,
                        "paid_cents": 100,
                        "lines": [],
                    }
                ]
            },
            token="secret",
        )
        assert again["skipped"] == 1
    finally:
        srv.stop()


def test_lan_sync_categories_and_barcode_queue(tmp_path):
    db_path = tmp_path / "hardware_pos.db"
    backup = tmp_path / "backups"
    bootstrap_database(db_path, backup)
    database = Database(db_path)
    # seed a category
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO categories(name, created_at, updated_at) VALUES ('水管', '2026-09-04', '2026-09-04')"
        )
    srv = LanSyncServer(database, host="127.0.0.1", port=18788, token="secret")
    srv.start()
    try:
        cats = _get("http://127.0.0.1:18788/api/v1/categories", token="secret")
        assert cats["ok"] is True
        assert any(c.get("name") == "水管" for c in cats["items"])
        pushed = _post(
            "http://127.0.0.1:18788/api/v1/barcode_queue",
            {
                "items": [
                    {
                        "barcode": "1234567890128",
                        "product_name": "测试商品",
                        "sku": "T1",
                        "copies": 2,
                    }
                ]
            },
            token="secret",
        )
        assert pushed["ok"] is True
        assert pushed["saved"] >= 1
        q = _get("http://127.0.0.1:18788/api/v1/barcode_queue", token="secret")
        assert q["ok"] is True
        assert any(i.get("barcode") == "1234567890128" for i in q["items"])
    finally:
        srv.stop()
