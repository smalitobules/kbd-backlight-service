from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from kbd_backlight_daemon import StateStore


class StateStoreTest(unittest.TestCase):
    def test_user_levels_are_persisted_per_uid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = StateStore(Path(directory), boot_level=1)
            device = Path("/sys/class/leds/asus::kbd_backlight")

            state.save_user_level(device, 1000, 3, 3)

            self.assertEqual(state.load_user_level(device, 1000, 3), 3)
            self.assertEqual(state.load_user_level(device, 1001, 3), 1)


if __name__ == "__main__":
    unittest.main()
