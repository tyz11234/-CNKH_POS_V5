from __future__ import annotations

from dataclasses import replace

from cnkh_pos.services.sales import SaleResult, SalesService


class CheckoutSalesService(SalesService):
    """SalesService adapter that returns the persisted cash-change value.

    The database trigger applies the shop's cash change rounding atomically inside
    the sale transaction. The base service computes the pre-trigger value in
    memory, so checkout reads the committed row back before presenting the result.
    """

    def create_sale(self, **kwargs) -> SaleResult:
        result = super().create_sale(**kwargs)
        if str(kwargs.get("payment_method", "")).upper() != "CASH":
            return result
        conn = self.database.connect(readonly=True)
        try:
            row = conn.execute(
                "SELECT change_cents FROM sales WHERE id=?", (result.sale_id,)
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return result
        return replace(result, change_cents=int(row["change_cents"]))
