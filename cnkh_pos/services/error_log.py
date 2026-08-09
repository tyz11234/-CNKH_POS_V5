from __future__ import annotations

import re
import traceback
from datetime import datetime
from pathlib import Path

from cnkh_pos.config import APP_VERSION


_SENSITIVE = re.compile(
    r"(?i)(password|password_hash|authorization|token|secret)\s*[:=]\s*[^\s,;]+"
)


def _redact(text: str) -> str:
    return _SENSITIVE.sub(lambda match: match.group(1) + "=[REDACTED]", text)


def write_error_log(
    log_dir: Path,
    exc: BaseException,
    *,
    app_mode: str,
    username: str | None = None,
) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().astimezone()
    path = log_dir / f"error_{now:%Y%m%d}.log"
    trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    block = (
        f"Date/Time: {now.isoformat(timespec='seconds')}\n"
        f"App Version: {APP_VERSION}\n"
        f"Mode: {app_mode}\n"
        f"Username: {username or '(not logged in)'}\n"
        f"Exception Type: {type(exc).__name__}\n"
        f"Error Message: {_redact(str(exc))}\n"
        f"Module: {type(exc).__module__}\n"
        f"Traceback:\n{_redact(trace)}\n"
        f"{'=' * 72}\n"
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(block)
    return path
