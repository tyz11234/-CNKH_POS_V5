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

    required = (
        ROOT / "build" / "admin.spec",
        ROOT / "build" / "staff.spec",
        ROOT / "installer" / "CNKH_POS_V5.iss",
        ROOT / ".github" / "workflows" / "windows-release.yml",
        ROOT / "tools" / "windows_gui_acceptance.py",
    )
    missing_required = [str(path) for path in required if not path.is_file()]
    if missing_required:
        raise RuntimeError("Missing release files: " + ", ".join(missing_required))

    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    for relative in (
        "cnkh_pos/__init__.py",
        "pyproject.toml",
        "installer/CNKH_POS_V5.iss",
    ):
        if version not in (ROOT / relative).read_text(encoding="utf-8"):
            raise RuntimeError(f"Version mismatch in {relative}: expected {version}")
    workflow = (ROOT / ".github/workflows/windows-release.yml").read_text(
        encoding="utf-8"
    )
    for marker in (
        "QT_SCALE_FACTOR: \"1.0\"",
        "QT_SCALE_FACTOR: \"1.25\"",
        "QT_SCALE_FACTOR: \"1.5\"",
        "Silent install and installed self-tests",
        "CNKH_POS_SELF_TEST_REPORT",
        "-Wait -PassThru",
        "installed-admin.json",
        "installed-staff.json",
        "Installed EXE normal launch smoke test",
        "installed-normal-launch.json",
        "CNKH POS Admin Login",
        "CNKH POS Staff Login",
        "python -m unittest discover -s tests -v",
        "python -m compileall -q cnkh_pos tools tests admin_launcher.py staff_launcher.py",
        "SHA256SUMS.txt",
    ):
        if marker not in workflow:
            raise RuntimeError(f"Windows release gate is missing: {marker}")
    if "$LASTEXITCODE" in workflow:
        raise RuntimeError(
            "Windows release gate must read exit codes from waited GUI processes"
        )

    from cnkh_pos.config import SCHEMA_VERSION
    from cnkh_pos.database.bootstrap import bootstrap_database

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        result = bootstrap_database(root / "hardware_pos.db", root / "backups")
        conn = sqlite3.connect(result.database_path)
        try:
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
            assert conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='supplier_products'"
            ).fetchone()
            assert "opening_cash_cents" in {
                row[1] for row in conn.execute("PRAGMA table_info(daily_cash_closings)")
            }
            assert "refund_method" in {
                row[1] for row in conn.execute("PRAGMA table_info(sale_returns)")
            }
        finally:
            conn.close()
    print(
        f"SOURCE SELF-TEST PASSED: {len(python_files)} Python files, schema {SCHEMA_VERSION}, version {version}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
