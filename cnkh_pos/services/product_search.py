from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass(frozen=True, slots=True)
class ProductSearchResult:
    product_id: int
    name: str
    sku: str
    barcode: str
    price_cents: int
    stock: str
    unit: str
    score: float
    exact_barcode: bool


def search_products(
    conn: sqlite3.Connection, query: str, *, limit: int = 3
) -> list[ProductSearchResult]:
    term = query.strip().casefold()
    if not term or limit < 1:
        return []
    like = f"%{term}%"
    rows = conn.execute(
        """
        SELECT p.id, p.name, p.aliases, COALESCE(c.name, '') category,
               COALESCE(p.sku, '') sku, COALESCE(p.barcode, '') barcode,
               p.selling_price_cents, p.stock_decimal, p.unit, p.location
        FROM products p
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE p.is_deleted = 0 AND (
            lower(p.name) LIKE ? OR lower(p.aliases) LIKE ? OR
            lower(COALESCE(p.sku, '')) LIKE ? OR lower(COALESCE(p.barcode, '')) LIKE ? OR
            lower(COALESCE(c.name, '')) LIKE ? OR lower(p.location) LIKE ?
        )
        LIMIT 80
        """,
        (like, like, like, like, like, like),
    ).fetchall()
    results: list[ProductSearchResult] = []
    for row in rows:
        fields = [
            str(row[key])
            for key in ("name", "aliases", "category", "sku", "barcode", "location")
        ]
        exact = str(row["barcode"]).casefold() == term
        contains = max((1.0 if term in field.casefold() else 0.0) for field in fields)
        similarity = max(
            SequenceMatcher(None, term, field.casefold()).ratio()
            for field in fields
            if field
        )
        score = 1000.0 if exact else contains * 100.0 + similarity
        results.append(
            ProductSearchResult(
                product_id=int(row["id"]),
                name=str(row["name"]),
                sku=str(row["sku"]),
                barcode=str(row["barcode"]),
                price_cents=int(row["selling_price_cents"]),
                stock=str(row["stock_decimal"]),
                unit=str(row["unit"]),
                score=score,
                exact_barcode=exact,
            )
        )
    return sorted(results, key=lambda item: (-item.score, item.name.casefold()))[:limit]
