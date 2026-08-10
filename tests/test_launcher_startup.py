from __future__ import annotations

import importlib
import sys
import types
import unittest
from unittest.mock import patch


class LauncherStartupTests(unittest.TestCase):
    def _assert_role_window_is_lazy(self, launcher_name: str, role_module: str, mode: str) -> None:
        launcher = importlib.import_module(launcher_name)
        fake_application = types.ModuleType("cnkh_pos.application")
        calls: list[tuple[str, object]] = []

        def run_application(received_mode: str, factory):
            calls.append((received_mode, factory))
            return 23

        fake_application.run_application = run_application
        original_import = __import__

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == role_module:
                raise AssertionError(f"{role_module} imported before authentication")
            return original_import(name, globals, locals, fromlist, level)

        argv = [launcher_name + ".py"]
        with patch.dict(sys.modules, {"cnkh_pos.application": fake_application}), patch(
            "builtins.__import__", side_effect=guarded_import
        ), patch.object(sys, "argv", argv):
            self.assertEqual(launcher.main(), 23)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], mode)
        self.assertTrue(callable(calls[0][1]))

    def test_admin_window_import_is_deferred_until_after_login(self) -> None:
        self._assert_role_window_is_lazy("admin_launcher", "cnkh_pos.ui.admin", "admin")

    def test_staff_window_import_is_deferred_until_after_login(self) -> None:
        self._assert_role_window_is_lazy("staff_launcher", "cnkh_pos.ui.staff", "staff")


if __name__ == "__main__":
    unittest.main()
