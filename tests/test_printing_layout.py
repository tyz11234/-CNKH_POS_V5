from cnkh_pos.services.printing import PrintingService, Receipt


def _receipt() -> Receipt:
    return Receipt(
        sale_id=1,
        receipt_no="CNKH20260810-001",
        sold_at="2026-08-10T20:00:00+08:00",
        cashier="Cashier",
        payment_method="CASH",
        subtotal_cents=283,
        discount_cents=0,
        total_cents=283,
        paid_cents=500,
        change_cents=217,
        items=(
            {
                "product_name_snapshot": "PVC Cable 4mm",
                "quantity_decimal": "1",
                "unit_snapshot": "meter",
                "unit_price_cents": 283,
                "discount_cents": 0,
                "subtotal_cents": 283,
            },
        ),
        settings={
            "store_name": "CNKH Hardware",
            "address": "",
            "phone": "",
            "footer": "Thank you / 谢谢光临",
            "notes": "",
        },
    )


def test_qt_receipt_html_uses_dedicated_right_aligned_amount_column() -> None:
    rendered = PrintingService.render_html(_receipt())
    assert 'td class="amount"' in rendered
    assert "text-align: right" in rendered
    assert "table-layout: fixed" in rendered
    for amount in ("RM 2.83", "RM 5.00", "RM 2.17"):
        assert amount in rendered


def test_qt_receipt_html_does_not_position_amounts_with_preformatted_spaces() -> None:
    rendered = PrintingService.render_html(_receipt())
    assert "<pre" not in rendered.lower()
    assert '<table class="summary">' in rendered
    assert '<table class="summary total">' in rendered
