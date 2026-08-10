from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


def rm_to_cents(value: str | int | Decimal) -> int:
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("invalid MYR amount") from exc
    cents = int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if cents < 0:
        raise ValueError("amount cannot be negative")
    return cents


def line_amount_cents(unit_price_cents: int, quantity: Decimal) -> int:
    """Return a quantity-adjusted line amount using the POS half-up cents rule."""
    amount = Decimal(int(unit_price_cents)) * Decimal(str(quantity))
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def clamp_discount_cents(discount_cents: int, line_cents: int) -> int:
    """Clamp a line discount so quantity edits can never make the line negative."""
    return max(0, min(int(discount_cents), max(0, int(line_cents))))


def round_checkout_cents(cents: int) -> int:
    """Apply CNKH checkout rounding to the final non-credit payable amount.

    Last sen digit 1-4 rounds down to 0, 5 stays unchanged, and 6-9 rounds
    up to the next 10 sen. Examples: 42 -> 40, 45 -> 45, 67 -> 70.
    """
    value = int(cents)
    if value < 0:
        raise ValueError("checkout amount cannot be negative")
    remainder = value % 10
    if remainder == 0 or remainder == 5:
        return value
    if 1 <= remainder <= 4:
        return value - remainder
    return value + (10 - remainder)


def checkout_rounding_cents(cents: int) -> int:
    """Return the signed adjustment applied by :func:`round_checkout_cents`."""
    value = int(cents)
    return round_checkout_cents(value) - value


def format_myr(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    absolute = abs(int(cents))
    return f"{sign}RM {absolute // 100:,}.{absolute % 100:02d}"
