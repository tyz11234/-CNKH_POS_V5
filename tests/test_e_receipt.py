from cnkh_pos.services.e_receipt import (
    build_e_receipt_text,
    normalize_my_phone,
    short_whatsapp_caption,
    whatsapp_url,
)
from cnkh_pos.services.printing import Receipt


def test_normalize_my_phone():
    assert normalize_my_phone("012-345 6789") == "60123456789"
    assert normalize_my_phone("+60 12-3456789") == "60123456789"
    assert normalize_my_phone("60123456789") == "60123456789"
    assert normalize_my_phone("") == ""


def test_build_e_receipt_text_print_style():
    text = build_e_receipt_text(
        receipt_no="R001",
        sold_at="2026-09-04T10:00:00",
        payment_method="CASH",
        total_cents=1500,
        lines=[
            {
                "name": "Hammer",
                "qty": 1,
                "unit_price_cents": 1500,
                "subtotal_cents": 1500,
            }
        ],
    )
    assert "CNKH Hardware" in text
    assert "Receipt: R001" in text
    assert "Hammer" in text
    assert "TOTAL" in text
    assert "Payment: CASH" in text


def test_whatsapp_url():
    url = whatsapp_url("0123456789", "hi there")
    assert url.startswith("https://wa.me/60123456789?text=")
    assert "hi%20there" in url or "hi+there" in url


def test_short_caption():
    receipt = Receipt(
        sale_id=1,
        receipt_no="R9",
        sold_at="2026-09-04T10:00:00",
        cashier="staff",
        payment_method="CASH",
        subtotal_cents=100,
        discount_cents=0,
        total_cents=100,
        paid_cents=100,
        change_cents=0,
        items=(),
        settings={"store_name": "CNKH Hardware"},
    )
    cap = short_whatsapp_caption(receipt)
    assert "PDF" in cap
    assert "R9" in cap
