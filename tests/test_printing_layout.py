import unicodedata
from dataclasses import replace

from cnkh_pos.services.printing import (
    RECEIPT_PDF_CJK_FONT,
    RECEIPT_TEXT_WIDTH,
    PrintingService,
    Receipt,
)


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


def _display_width(text: str) -> int:
    return sum(
        2 if unicodedata.east_asian_width(character) in {"W", "F"} else 1
        for character in text
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


def test_qt_receipt_html_declares_cjk_font_fallbacks() -> None:
    rendered = PrintingService.render_html(_receipt())
    assert "Microsoft YaHei UI" in rendered
    assert "SimSun" in rendered


def test_plain_receipt_respects_cjk_display_width_and_keeps_amounts() -> None:
    receipt = replace(
        _receipt(),
        settings={
            **_receipt().settings,
            "store_name": "CNKH 五金 Hardware Store 超长店名",
            "address": "No. 1 Hardware Road\n雪兰莪 Malaysia",
            "footer": "Thank you / 谢谢光临，欢迎再次惠顾",
            "notes": "测试多语言 80mm receipt output",
        },
    )
    rendered = PrintingService.render_text(receipt)
    assert "谢谢光临" in rendered
    assert max(_display_width(line) for line in rendered.splitlines()) <= RECEIPT_TEXT_WIDTH
    for amount in ("RM 2.83", "RM 5.00", "RM 2.17"):
        assert amount in rendered


def test_reportlab_receipt_pdf_uses_cjk_font(tmp_path) -> None:
    receipt = replace(
        _receipt(),
        settings={**_receipt().settings, "footer": "Thank you / 谢谢光临"},
    )
    output = PrintingService(database=None).render_pdf(receipt, tmp_path / "receipt.pdf")
    assert output.is_file()
    assert output.stat().st_size > 500
    assert f"/{RECEIPT_PDF_CJK_FONT}".encode() in output.read_bytes()
