from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation


def discount_cents_from_value(
    gross_cents: int,
    *,
    mode: str,
    value: str | int | float | Decimal,
) -> int:
    gross = int(gross_cents)
    if gross < 0:
        raise ValueError("gross amount cannot be negative")
    normalized = mode.strip().upper()
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("invalid discount value") from exc
    if number < 0:
        raise ValueError("discount cannot be negative")
    if normalized == "PERCENT":
        if number > 100:
            raise ValueError("discount percentage cannot exceed 100")
        discount = int(
            (Decimal(gross) * number / Decimal(100)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
    elif normalized == "FIXED":
        discount = int(
            (number * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
    else:
        raise ValueError("unsupported discount mode")
    if discount > gross:
        raise ValueError("discount cannot exceed amount")
    return discount


def allocate_order_discount(
    line_net_cents: list[tuple[int, int]],
    discount_cents: int,
) -> dict[int, int]:
    """Proportionally allocate an exact order discount across line net amounts."""
    discount = int(discount_cents)
    if discount < 0:
        raise ValueError("discount cannot be negative")
    normalized = [(int(key), max(0, int(net))) for key, net in line_net_cents]
    total = sum(net for _key, net in normalized)
    if discount > total:
        raise ValueError("discount cannot exceed order total")
    if discount == 0 or total == 0:
        return {key: 0 for key, _net in normalized}

    allocations: dict[int, int] = {}
    fractions: list[tuple[Decimal, int]] = []
    allocated = 0
    for key, net in normalized:
        exact = Decimal(discount) * Decimal(net) / Decimal(total)
        base = int(exact.quantize(Decimal("1"), rounding=ROUND_DOWN))
        base = min(base, net)
        allocations[key] = base
        allocated += base
        fractions.append((exact - Decimal(base), key))

    remaining = discount - allocated
    for _fraction, key in sorted(fractions, key=lambda item: (-item[0], item[1])):
        if remaining <= 0:
            break
        capacity = dict(normalized)[key] - allocations[key]
        if capacity > 0:
            allocations[key] += 1
            remaining -= 1
    if remaining:
        for key, net in normalized:
            if remaining <= 0:
                break
            capacity = net - allocations[key]
            take = min(capacity, remaining)
            allocations[key] += take
            remaining -= take
    if remaining:
        raise RuntimeError("could not allocate complete order discount")
    return allocations
