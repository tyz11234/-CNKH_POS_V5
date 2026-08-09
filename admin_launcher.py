from __future__ import annotations

import sys


def main() -> int:
    if "--self-test" in sys.argv:
        from tools.packaged_self_test import run
        return run("admin")
    from cnkh_pos.application import run_application
    from cnkh_pos.ui.admin import AdminWindow

    return run_application("admin", lambda database, user: AdminWindow(database, user))


if __name__ == "__main__":
    raise SystemExit(main())
