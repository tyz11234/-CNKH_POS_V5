from __future__ import annotations

import sys


def main() -> int:
    if "--self-test" in sys.argv:
        from tools.packaged_self_test import run
        return run("admin")
    from cnkh_pos.application import run_application

    def build_window(database, user):
        # Keep the login path fast, especially for the PyInstaller one-file build.
        # AdminWindow imports all Admin pages plus Excel/PDF dependencies, so load it
        # only after authentication has succeeded.
        from cnkh_pos.ui.admin import AdminWindow

        return AdminWindow(database, user)

    return run_application("admin", build_window)


if __name__ == "__main__":
    raise SystemExit(main())
