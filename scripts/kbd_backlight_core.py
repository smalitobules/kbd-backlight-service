from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


def clamp_level(level: int, max_brightness: int) -> int:
    if max_brightness <= 0:
        raise ValueError("max_brightness must be greater than 0.")
    return min(max(level, 0), max_brightness)


def clamp_percent(percent: int) -> int:
    return min(max(percent, 0), 100)


def level_to_percent(level: int, max_brightness: int) -> int:
    if max_brightness <= 0:
        raise ValueError("max_brightness must be greater than 0.")
    return clamp_percent((clamp_level(level, max_brightness) * 100) // max_brightness)


def percent_to_level(percent: int, max_brightness: int) -> int:
    if max_brightness <= 0:
        raise ValueError("max_brightness must be greater than 0.")
    normalized = clamp_percent(percent)
    if normalized <= 0:
        return 0
    level = (normalized * max_brightness + 50) // 100
    return clamp_level(max(level, 1), max_brightness)


def clamp_boot_level(level: int, max_brightness: int | None = None) -> int:
    minimum = 1
    normalized = max(level, minimum)
    if max_brightness is None:
        return normalized
    return min(normalized, max(max_brightness, minimum))


def state_name_for_device(device: Path) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", device.name)


@dataclass(frozen=True)
class ObservationResult:
    manual_change: bool = False
    manual_off: bool = False
    visible_level: int | None = None


@dataclass
class BacklightDecision:
    boot_level: int
    last_nonzero_level: int = 1
    desired_levels: dict[int, int] = field(default_factory=dict)
    dimmed_flags: dict[int, bool] = field(default_factory=dict)
    manual_off_flags: dict[int, bool] = field(default_factory=dict)
    managed_levels: dict[int, int] = field(default_factory=dict)
    seen_levels: dict[int, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.boot_level = clamp_boot_level(self.boot_level)
        self.last_nonzero_level = clamp_boot_level(self.last_nonzero_level)

    def target_for_uid(self, uid: int) -> int:
        return self.desired_levels.get(uid, self.boot_level)

    def remember_visible_level(self, uid: int, level: int) -> None:
        if level <= 0:
            return
        self.desired_levels[uid] = level
        self.last_nonzero_level = level

    def set_managed_level(self, uid: int, level: int) -> None:
        self.managed_levels[uid] = level

    def managed_level_for_uid(self, uid: int) -> int | None:
        return self.managed_levels.get(uid)

    def activation_level(self, uid: int, allow_manual_off: bool) -> int | None:
        if not allow_manual_off:
            return self.boot_level
        if self.manual_off_flags.get(uid, False):
            return 0
        return self.target_for_uid(uid)

    def finish_activation(self, uid: int, current_level: int, allow_manual_off: bool) -> None:
        self.seen_levels[uid] = current_level
        if allow_manual_off and current_level > 0:
            self.remember_visible_level(uid, current_level)
        self.dimmed_flags[uid] = False

    def observe(
        self,
        uid: int,
        current_level: int,
        allow_manual_off: bool,
    ) -> ObservationResult:
        previous_level = self.seen_levels.get(uid)
        managed_level = self.managed_levels.get(uid)
        manual_change = previous_level is not None and current_level != previous_level and current_level != managed_level
        if manual_change:
            return self.accept_external_level(uid, current_level, allow_manual_off, True)
        self.seen_levels[uid] = current_level
        return self.update_visible_state(uid, current_level, allow_manual_off, False)

    def accept_external_level(
        self,
        uid: int,
        current_level: int,
        allow_manual_off: bool,
        manual_change: bool,
    ) -> ObservationResult:
        self.seen_levels[uid] = current_level
        return self.update_visible_state(uid, current_level, allow_manual_off, manual_change)

    def update_visible_state(
        self,
        uid: int,
        current_level: int,
        allow_manual_off: bool,
        manual_change: bool,
    ) -> ObservationResult:
        manual_off = False
        visible_level: int | None = None
        if current_level > 0 and allow_manual_off:
            self.remember_visible_level(uid, current_level)
            self.dimmed_flags[uid] = False
            visible_level = current_level
            self.manual_off_flags[uid] = False
        elif allow_manual_off and not self.dimmed_flags.get(uid, False):
            self.manual_off_flags[uid] = True
            manual_off = True
        return ObservationResult(
            manual_change=manual_change,
            manual_off=manual_off,
            visible_level=visible_level,
        )

    def idle_transition(self, uid: int, current_level: int) -> int | None:
        if self.manual_off_flags.get(uid, False):
            self.dimmed_flags[uid] = False
            return None
        if self.dimmed_flags.get(uid, False):
            return None
        if current_level > 0:
            self.remember_visible_level(uid, current_level)
            self.dimmed_flags[uid] = True
            return 0
        return None

    def activity_transition(self, uid: int, current_level: int, allow_manual_off: bool) -> int | None:
        if not allow_manual_off:
            return None
        if self.dimmed_flags.get(uid, False):
            self.dimmed_flags[uid] = False
            self.manual_off_flags[uid] = False
            if current_level > 0:
                self.remember_visible_level(uid, current_level)
                return None
            return self.target_for_uid(uid)
        if current_level > 0:
            self.remember_visible_level(uid, current_level)
            self.manual_off_flags[uid] = False
            return None
        self.manual_off_flags[uid] = True
        return None

    def boot_candidate_for_uid(self, uid: int, current_level: int) -> int:
        if current_level > 0:
            return current_level
        if self.manual_off_flags.get(uid, False):
            return 1
        return self.target_for_uid(uid)
