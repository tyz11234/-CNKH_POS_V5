from __future__ import annotations

from cnkh_pos.database.connection import Database
from cnkh_pos.database.migrations import utc_now_text
from cnkh_pos.database.repositories import SupplierPaymentRepository
from cnkh_pos.services.audit import AuditService


class PaymentError(RuntimeError):
    pass


class CustomerPaymentService:
    def __init__(self, database: Database):
        self.database = database

    def record_payment(
        self,
        *,
        debt_id: int,
        amount_cents: int,
        payment_method: str,
        note: str,
        operator_id: int,
    ) -> int:
        if amount_cents <= 0:
            raise PaymentError("payment must be positive")
        with self.database.transaction() as conn:
            debt = conn.execute(
                "SELECT * FROM customer_debts WHERE id=?", (debt_id,)
            ).fetchone()
            if debt is None:
                raise LookupError("customer debt not found")
            if debt["status"] == "CLOSED" or amount_cents > int(debt["balance_cents"]):
                raise PaymentError("payment exceeds open balance")
            now = utc_now_text()
            new_balance = int(debt["balance_cents"]) - amount_cents
            status = "CLOSED" if new_balance == 0 else "OPEN"
            cursor = conn.execute(
                """INSERT INTO customer_payments(
                    customer_id, amount_cents, payment_method, note, operator_id, paid_at, debt_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    debt["customer_id"],
                    amount_cents,
                    payment_method.upper(),
                    note,
                    operator_id,
                    now,
                    debt_id,
                ),
            )
            conn.execute(
                "UPDATE customer_debts SET balance_cents=?, status=?, settled_at=? WHERE id=?",
                (new_balance, status, now if status == "CLOSED" else None, debt_id),
            )
            payment_id = int(cursor.lastrowid)
            AuditService.record(
                conn,
                action="CUSTOMER_PAYMENT",
                module="CUSTOMERS",
                user_id=operator_id,
                record_type="CUSTOMER_DEBT",
                record_id=debt_id,
                old_value={
                    "balance_cents": debt["balance_cents"],
                    "status": debt["status"],
                },
                new_value={
                    "balance_cents": new_balance,
                    "status": status,
                    "payment_id": payment_id,
                },
            )
            return payment_id


class SupplierPaymentService:
    def __init__(self, database: Database):
        self.database = database

    def record_payment(
        self,
        *,
        purchase_id: int,
        amount_cents: int,
        payment_method: str,
        note: str,
        operator_id: int,
    ) -> int:
        if amount_cents <= 0:
            raise PaymentError("payment must be positive")
        with self.database.transaction() as conn:
            purchase = conn.execute(
                "SELECT * FROM purchases WHERE id=?", (purchase_id,)
            ).fetchone()
            if purchase is None:
                raise LookupError("purchase not found")
            remaining = int(purchase["total_cents"]) - int(purchase["paid_cents"])
            if amount_cents > remaining:
                raise PaymentError("payment exceeds supplier balance")
            payment_id = SupplierPaymentRepository.add(
                conn,
                supplier_id=int(purchase["supplier_id"]),
                purchase_id=purchase_id,
                amount_cents=amount_cents,
                payment_method=payment_method,
                note=note,
                operator_id=operator_id,
            )
            new_paid = int(purchase["paid_cents"]) + amount_cents
            status = "PAID" if new_paid == int(purchase["total_cents"]) else "PARTIAL"
            conn.execute(
                "UPDATE purchases SET paid_cents=?, status=? WHERE id=?",
                (new_paid, status, purchase_id),
            )
            AuditService.record(
                conn,
                action="SUPPLIER_PAYMENT",
                module="SUPPLIERS",
                user_id=operator_id,
                record_type="PURCHASE",
                record_id=purchase_id,
                old_value={
                    "paid_cents": purchase["paid_cents"],
                    "status": purchase["status"],
                },
                new_value={
                    "paid_cents": new_paid,
                    "status": status,
                    "payment_id": payment_id,
                },
            )
            return payment_id
