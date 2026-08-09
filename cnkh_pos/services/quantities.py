from __future__ import annotations

from decimal import Decimal, InvalidOperation


def parse_quantity(value: str | int | Decimal, *, allow_zero: bool = True) -> Decimal:
    result = parse_signed_quantity(value)
    if result < 0 or (not allow_zero and result == 0):
        raise ValueError("quantity must be positive")
    return result


def parse_signed_quantity(value: str | int | Decimal) -> Decimal:
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("invalid quantity") from exc
    if not result.is_finite():
        raise ValueError("quantity must be finite")
    return result


def quantity_text(value: Decimal) -> str:
    normalized = value.normalize()
    return format(normalized, "f") if normalized != 0 else "0"
