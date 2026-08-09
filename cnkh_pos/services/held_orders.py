from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from cnkh_pos.database.connection import Database
from cnkh_pos.database.migrations import utc_now_text
from cnkh_pos.services.audit import AuditService
from cnkh_pos.services.document_numbers import next_document_number


@dataclass(frozen=True, slots=True)
class HeldOrder:
    id: int
    hold_no: str
    payload: dict[str, object]


def cart_state_from_held_payload(
    payload: dict[str, object],
) -> tuple[dict[int, Decimal], dict[int, int]]:
    """Restore canonical cart state from a held-order payload.

    Zero-value discounts are intentionally omitted.  The live cart uses a
    sparse discount mapping, so adding ``product_id: 0`` entries while
    retrieving an order would make the restored state differ from the state
    that was held even though the payable total is unchanged.
    """
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("invalid held-order items")

    quantities: dict[int, Decimal] = {}
    discounts: dict[int, int] = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("invalid held-order item")
        product_id = int(item["product_id"])
        quantity = Decimal(str(item["quantity"]))
        discount_cents = int(item.get("discount_cents", 0))
        if quantity <= 0 or discount_cents < 0:
            raise ValueError("invalid held-order quantity or discount")
        quantities[product_id] = quantity
        if discount_cents:
            discounts[product_id] = discount_cents
    return quantities, discounts


class HeldOrderService:
    def __init__(self, database: Database):
        self.database = database

    def hold(self, payload: dict[str, object], *, cashier_id: int) -> HeldOrder:
        if not payload.get("items"):
            raise ValueError("cannot hold an empty cart")
        with self.database.transaction() as conn:
            number = next_document_number(conn, "HOLD", date.today(), "HOLD-")
            cursor = conn.execute(
                "INSERT INTO held_orders(hold_no,payload_json,cashier_id,held_at) VALUES (?,?,?,?)",
                (
                    number,
                    json.dumps(payload, sort_keys=True),
                    cashier_id,
                    utc_now_text(),
                ),
            )
            held_id = int(cursor.lastrowid)
            AuditService.record(
                conn,
                action="HOLD",
                module="POS",
                user_id=cashier_id,
                record_type="HELD_ORDER",
                record_id=held_id,
                new_value={"hold_no": number},
            )
            return HeldOrder(held_id, number, payload)

    def retrieve_latest(self, *, cashier_id: int) -> HeldOrder:
        with self.database.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM held_orders WHERE status='HELD' ORDER BY held_at DESC,id DESC LIMIT 1"
            ).fetchone()
            if row is None:
                raise LookupError("no held order")
            conn.execute(
                "UPDATE held_orders SET status='RETRIEVED',retrieved_at=? WHERE id=?",
                (utc_now_text(), row["id"]),
            )
            AuditService.record(
                conn,
                action="RETRIEVE",
                module="POS",
                user_id=cashier_id,
                record_type="HELD_ORDER",
                record_id=row["id"],
            )
            return HeldOrder(
                int(row["id"]), str(row["hold_no"]), json.loads(row["payload_json"])
            )
