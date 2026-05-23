from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from kbd_backlight_daemon import ConfigurationError
from kbd_backlight_daemon import StateStore


class StateStoreTest(unittest.TestCase):
    def test_user_levels_are_persisted_per_uid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = StateStore(Path(directory), boot_level=1)
            device = Path("/sys/class/leds/asus::kbd_backlight")

            state.save_user_level(device, 1000, 3, 3)

            self.assertEqual(state.load_user_level(device, 1000, 3), 3)
            self.assertEqual(state.load_user_level(device, 1001, 3), 1)

    def test_invalid_user_level_falls_back_to_boot_level(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = StateStore(Path(directory), boot_level=1)
            device = Path("/sys/class/leds/asus::kbd_backlight")
            state.prepare()
            state.user_file_for_device(device, 1000).write_text("invalid\n", encoding="ascii")

            self.assertEqual(state.load_user_level(device, 1000, 3), 1)

    def test_symlink_user_level_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = StateStore(Path(directory), boot_level=1)
            device = Path("/sys/class/leds/asus::kbd_backlight")
            state.prepare()
            target = Path(directory) / "target.level"
            target.write_text("3\n", encoding="ascii")
            state.user_file_for_device(device, 1000).symlink_to(target)

            with self.assertRaises(ConfigurationError):
                state.load_user_level(device, 1000, 3)


if __name__ == "__main__":
    unittest.main()
