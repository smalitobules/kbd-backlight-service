from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from kbd_backlight_core import level_to_percent, percent_to_level


class MappingTest(unittest.TestCase):
    def test_raw_levels_to_percent(self) -> None:
        self.assertEqual(level_to_percent(0, 3), 0)
        self.assertEqual(level_to_percent(1, 3), 33)
        self.assertEqual(level_to_percent(2, 3), 66)
        self.assertEqual(level_to_percent(3, 3), 100)

    def test_percent_to_raw_levels(self) -> None:
        self.assertEqual(percent_to_level(0, 3), 0)
        self.assertEqual(percent_to_level(33, 3), 1)
        self.assertEqual(percent_to_level(1, 3), 1)


if __name__ == "__main__":
    unittest.main()
