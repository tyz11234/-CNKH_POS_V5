from __future__ import annotations

import sys


def main() -> int:
    if "--self-test" in sys.argv:
        from tools.packaged_self_test import run
        return run("staff")
    from cnkh_pos.application import run_application

    def build_window(database, user):
        # Keep role-window imports out of the pre-login startup path for consistent
        # packaged EXE behaviour.
        from cnkh_pos.ui.staff import StaffWindow

        return StaffWindow(database, user)

    return run_application("staff", build_window)


if __name__ == "__main__":
    raise SystemExit(main())
