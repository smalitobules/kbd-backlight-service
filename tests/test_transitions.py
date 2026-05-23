from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from kbd_backlight_core import BacklightDecision


class TransitionTest(unittest.TestCase):
    def test_manual_zero_in_unlocked_session_stays_off(self) -> None:
        decision = BacklightDecision(boot_level=1, last_nonzero_level=2)
        uid = 1000
        decision.finish_activation(uid, 2, allow_manual_off=True)

        result = decision.observe(uid, 0, allow_manual_off=True)

        self.assertTrue(result.manual_change)
        self.assertTrue(result.manual_off)
        self.assertIsNone(decision.idle_transition(uid, 0))
        self.assertIsNone(decision.activity_transition(uid, 0, allow_manual_off=True))

    def test_idle_transition_dims_once(self) -> None:
        decision = BacklightDecision(boot_level=1, last_nonzero_level=2)
        uid = 1000

        self.assertEqual(decision.idle_transition(uid, 2), 0)
        self.assertIsNone(decision.idle_transition(uid, 0))

    def test_activity_transition_restores_once(self) -> None:
        decision = BacklightDecision(boot_level=1, last_nonzero_level=2)
        uid = 1000
        self.assertEqual(decision.idle_transition(uid, 2), 0)

        self.assertEqual(decision.activity_transition(uid, 0, allow_manual_off=True), 2)
        self.assertIsNone(decision.activity_transition(uid, 2, allow_manual_off=True))

    def test_observed_managed_idle_zero_still_restores_on_activity(self) -> None:
        decision = BacklightDecision(boot_level=1, last_nonzero_level=2)
        uid = 1000
        decision.finish_activation(uid, 2, allow_manual_off=True)
        self.assertEqual(decision.idle_transition(uid, 2), 0)
        decision.set_managed_level(uid, 0)

        result = decision.observe(uid, 0, allow_manual_off=True)

        self.assertFalse(result.manual_off)
        self.assertEqual(decision.activity_transition(uid, 0, allow_manual_off=True), 2)

    def test_locked_positive_change_does_not_override_account_level(self) -> None:
        decision = BacklightDecision(boot_level=1, last_nonzero_level=1)
        uid = 1000
        decision.finish_activation(uid, 3, allow_manual_off=True)

        decision.accept_external_level(
            uid,
            2,
            allow_manual_off=False,
            manual_change=True,
        )

        self.assertEqual(decision.target_for_uid(uid), 3)

    def test_locked_activation_uses_boot_level(self) -> None:
        decision = BacklightDecision(boot_level=1, last_nonzero_level=2)
        uid = 1000

        self.assertEqual(decision.activation_level(uid, allow_manual_off=False), 1)
        self.assertIsNone(decision.activity_transition(uid, 3, allow_manual_off=False))

    def test_greeter_entry_uses_boot_level_without_overriding_user(self) -> None:
        decision = BacklightDecision(boot_level=1, last_nonzero_level=1)
        user_uid = 1000
        greeter_uid = 120
        decision.finish_activation(user_uid, 3, allow_manual_off=True)

        decision.accept_external_level(
            greeter_uid,
            3,
            allow_manual_off=False,
            manual_change=False,
        )

        self.assertEqual(decision.target_for_uid(user_uid), 3)
        self.assertEqual(decision.activation_level(greeter_uid, allow_manual_off=False), 1)
        self.assertIsNone(decision.activity_transition(greeter_uid, 3, allow_manual_off=False))

    def test_greeter_positive_manual_change_does_not_override_account_level(self) -> None:
        decision = BacklightDecision(boot_level=1, last_nonzero_level=1)
        user_uid = 1000
        greeter_uid = 120
        decision.finish_activation(user_uid, 3, allow_manual_off=True)

        decision.accept_external_level(
            greeter_uid,
            1,
            allow_manual_off=False,
            manual_change=True,
        )

        self.assertEqual(decision.target_for_uid(user_uid), 3)

    def test_accounts_do_not_inherit_other_account_levels(self) -> None:
        decision = BacklightDecision(boot_level=1, last_nonzero_level=1)
        first_uid = 1000
        second_uid = 1001
        decision.finish_activation(first_uid, 3, allow_manual_off=True)

        self.assertEqual(decision.target_for_uid(first_uid), 3)
        self.assertEqual(decision.target_for_uid(second_uid), 1)


if __name__ == "__main__":
    unittest.main()
