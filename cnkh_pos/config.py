from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from cnkh_pos import __version__

APP_NAME = "CNKH Hardware POS"
SCHEMA_VERSION = 8


def _local_app_data() -> Path:
    value = os.environ.get("LOCALAPPDATA")
    if value:
        return Path(value)
    # Non-Windows fallback is used only for development and tests.
    return Path.home() / ".local" / "share"


RECEIPT_QR_IMAGE_NAME = "receipt_qr.png"


@dataclass(frozen=True, slots=True)
class AppPaths:
    root: Path
    data: Path
    database: Path
    backups: Path
    logs: Path
    exports: Path
    receipts: Path
    assets: Path

    @classmethod
    def default(cls) -> AppPaths:
        root = _local_app_data() / APP_NAME
        return cls(
            root=root,
            data=root / "Data",
            database=root / "Data" / "hardware_pos.db",
            backups=root / "Backups",
            logs=root / "Logs",
            exports=root / "Exports",
            receipts=root / "Receipts",
            assets=root / "Assets",
        )

    @property
    def receipt_qr_image(self) -> Path:
        return self.assets / RECEIPT_QR_IMAGE_NAME

    def ensure_directories(self) -> None:
        for folder in (
            self.root,
            self.data,
            self.backups,
            self.logs,
            self.exports,
            self.receipts,
            self.assets,
        ):
            folder.mkdir(parents=True, exist_ok=True)


APP_VERSION = __version__
