from pathlib import Path


def test_cart_quantity_controls_override_global_button_padding() -> None:
    qss = Path("resources/styles/app.qss").read_text(encoding="utf-8")
    selector = "QPushButton#CartQuantityMinus, QPushButton#CartQuantityPlus"
    assert selector in qss
    block = qss.split(selector, 1)[1].split("}", 1)[0]
    assert "padding: 0" in block
    assert "min-height: 32px" in block
    assert "font-size: 16px" in block


def test_cart_quantity_spinbox_has_compact_high_dpi_padding() -> None:
    qss = Path("resources/styles/app.qss").read_text(encoding="utf-8")
    selector = "QDoubleSpinBox#CartQuantityValue"
    assert selector in qss
    block = qss.split(selector, 1)[1].split("}", 1)[0]
    assert "padding-left: 2px" in block
    assert "padding-right: 2px" in block
