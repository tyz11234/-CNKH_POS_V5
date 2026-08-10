from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


def discount_from_percent_cents(line_cents: int, percent: str | int | float | Decimal) -> int:
    """Return a line discount from a 0-100 percentage using half-up cents."""
    maximum = max(0, int(line_cents))
    try:
        rate = Decimal(str(percent))
    except InvalidOperation as exc:
        raise ValueError("invalid discount percentage") from exc
    if rate < 0 or rate > 100:
        raise ValueError("discount percentage must be between 0 and 100")
    discount = int(
        (Decimal(maximum) * rate / Decimal("100")).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    return min(maximum, max(0, discount))


def discount_from_amount_cents(line_cents: int, amount_cents: int) -> int:
    """Clamp a fixed-money discount to the current line amount."""
    maximum = max(0, int(line_cents))
    amount = int(amount_cents)
    if amount < 0:
        raise ValueError("discount amount cannot be negative")
    return min(maximum, amount)
