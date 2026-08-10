from __future__ import annotations

import re
from pathlib import Path

import pytest

from cnkh_pos.services.barcode_labels import (
    LABEL_PROFILES,
    ProductLabel,
    barcode_symbology,
    get_label_profile,
    normalize_barcode,
    render_product_label_pdf,
    validate_copy_count,
)


def _label(barcode: str = "9551234567891") -> ProductLabel:
    return ProductLabel(
        product_id=1,
        name="PVC 电线 4mm",
        sku="PVC-4MM",
        barcode=barcode,
        price_cents=1280,
    )


def test_50x30_profile_is_required_product_label_size() -> None:
    profile = get_label_profile("50x30")
    assert profile.width_mm == 50.0
    assert profile.height_mm == 30.0
    assert {profile.key for profile in LABEL_PROFILES} == {
        "35x25",
        "40x30",
        "50x30",
        "60x40",
    }


def test_copy_count_is_user_configurable_but_bounded() -> None:
    assert validate_copy_count(1) == 1
    assert validate_copy_count(25) == 25
    assert validate_copy_count(999) == 999
    with pytest.raises(ValueError):
        validate_copy_count(0)
    with pytest.raises(ValueError):
        validate_copy_count(1000)


def test_ean13_is_used_only_when_checksum_is_valid() -> None:
    assert barcode_symbology("4006381333931") == "EAN13"
    assert barcode_symbology("4006381333932") == "Code128"
    assert barcode_symbology("CNKH-ABC-001") == "Code128"


def test_empty_or_unprintable_barcode_is_rejected() -> None:
    with pytest.raises(ValueError):
        normalize_barcode("")
    with pytest.raises(ValueError):
        normalize_barcode("ABC\n123")


def test_pdf_preview_uses_one_page_per_requested_label(tmp_path: Path) -> None:
    output = render_product_label_pdf(
        _label("4006381333931"),
        get_label_profile("50x30"),
        4,
        tmp_path / "labels.pdf",
    )
    payload = output.read_bytes()
    assert output.stat().st_size > 1000
    page_objects = re.findall(rb"/Type\s*/Page\b", payload)
    assert len(page_objects) == 4


def test_compact_and_large_profiles_generate_pdf(tmp_path: Path) -> None:
    for profile_key in ("35x25", "60x40"):
        output = render_product_label_pdf(
            _label("CNKH-ABC-001"),
            get_label_profile(profile_key),
            1,
            tmp_path / f"{profile_key}.pdf",
        )
        assert output.is_file()
        assert output.stat().st_size > 900
