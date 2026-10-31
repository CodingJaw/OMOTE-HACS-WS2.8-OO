"""Check that read-only panel cannot expose credential files or traversal paths."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "omote_manager"
PACKAGE = "omote_test_package"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package

def load(name):
    spec = importlib.util.spec_from_file_location(PACKAGE + "." + name, ROOT / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

load("const")
safe = load("safe_files")


class TestFilePolicy(unittest.TestCase):
    def test_allowed_files(self):
        for name in (
            "Scenes.json",
            "Scenes/Scene_WatchTV.json",
            "Pages/Page_TV.json",
            "Commands/Commands_Roku.json",
            "Devices/ElementTv.json",
            "Actions/IRActionExample.json",
        ):
            with self.subTest(name=name):
                self.assertTrue(safe.is_exportable_json(name))

    def test_rejected_files(self):
        for name in (
            "HaSettings.json",
            "DeviceSettings.json",
            "ftp.json",
            "Pages/../../HaSettings.json",
            "/Scenes/Scene_WatchTV.json",
            "Scenes\\anything.json",
            "Pages/not-json.txt",
            "other/unknown.json",
            "Scenes/HASettings.json",
            "",
        ):
            with self.subTest(name=name):
                self.assertFalse(safe.is_exportable_json(name))


if __name__ == "__main__":
    unittest.main()
