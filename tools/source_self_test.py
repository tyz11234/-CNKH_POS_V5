from __future__ import annotations

import ast
import sqlite3
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    python_files = sorted(
        path
        for path in ROOT.rglob("*.py")
        if not any(
            part in {".testdeps", ".venv", "build", "dist"} for part in path.parts
        )
    )
    for path in python_files:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    qrc = ROOT / "resources" / "resources.qrc"
    tree = ET.parse(qrc)
    missing: list[str] = []
    for node in tree.findall(".//file"):
        resource_path = qrc.parent / (node.text or "")
        if not resource_path.exists():
            missing.append(str(resource_path))
    if missing:
        raise RuntimeError("Missing Qt resources: " + ", ".join(missing))

    from cnkh_pos.config import SCHEMA_VERSION
    from cnkh_pos.database.bootstrap import bootstrap_database

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        result = bootstrap_database(root / "hardware_pos.db", root / "backups")
        conn = sqlite3.connect(result.database_path)
        try:
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        finally:
            conn.close()
    print(
        f"SOURCE SELF-TEST PASSED: {len(python_files)} Python files, schema {SCHEMA_VERSION}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
