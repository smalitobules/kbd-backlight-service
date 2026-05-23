from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from kbd_backlight_daemon import DBusClient
from kbd_backlight_daemon import parse_uid
from kbd_backlight_daemon import worker_message_to_event


class DaemonProtocolTest(unittest.TestCase):
    def test_dbus_client_keeps_property_writer_method(self) -> None:
        self.assertTrue(callable(getattr(DBusClient, "set_int_property", None)))

    def test_parse_uid_rejects_bool(self) -> None:
        self.assertEqual(parse_uid(True), -1)
        self.assertEqual(parse_uid((False,)), -1)

    def test_worker_message_rejects_bool_in_integer_fields(self) -> None:
        event = worker_message_to_event(
            {
                "type": "event_brightness_changed",
                "session_id": "1",
                "uid": True,
                "percent": False,
            }
        )

        self.assertIsNone(event.uid)
        self.assertIsNone(event.percent)


if __name__ == "__main__":
    unittest.main()
