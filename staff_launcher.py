from __future__ import annotations

import sys


def main() -> int:
    if "--self-test" in sys.argv:
        from tools.packaged_self_test import run
        return run("staff")
    from cnkh_pos.application import run_application
    from cnkh_pos.ui.staff import StaffWindow

    return run_application("staff", lambda database, user: StaffWindow(database, user))


if __name__ == "__main__":
    raise SystemExit(main())
