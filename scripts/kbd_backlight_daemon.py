#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import glob
import json
import logging
import os
import pwd
import re
import signal
import sys
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

from kbd_backlight_core import BacklightDecision
from kbd_backlight_core import ObservationResult
from kbd_backlight_core import clamp_boot_level
from kbd_backlight_core import clamp_level
from kbd_backlight_core import clamp_percent
from kbd_backlight_core import level_to_percent
from kbd_backlight_core import percent_to_level
from kbd_backlight_core import state_name_for_device

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]

LOGIND_DESTINATION = "org.freedesktop.login1"
LOGIND_MANAGER_PATH = "/org/freedesktop/login1"
LOGIND_MANAGER_INTERFACE = "org.freedesktop.login1.Manager"
LOGIND_SESSION_INTERFACE = "org.freedesktop.login1.Session"
PROPERTIES_INTERFACE = "org.freedesktop.DBus.Properties"
DBUS_DESTINATION = "org.freedesktop.DBus"
DBUS_PATH = "/org/freedesktop/DBus"
DBUS_INTERFACE = "org.freedesktop.DBus"
MUTTER_DESTINATION = "org.gnome.Mutter.IdleMonitor"
MUTTER_PATH = "/org/gnome/Mutter/IdleMonitor/Core"
MUTTER_INTERFACE = "org.gnome.Mutter.IdleMonitor"
POWER_DESTINATION = "org.gnome.SettingsDaemon.Power"
POWER_PATH = "/org/gnome/SettingsDaemon/Power"
POWER_KEYBOARD_INTERFACE = "org.gnome.SettingsDaemon.Power.Keyboard"
DEFAULT_STATE_DIR = "/var/lib/kbd-backlight-service"
DEFAULT_DEVICE_GLOB = "/sys/class/leds/asus::kbd_backlight"
GRAPHICAL_SESSION_TYPES = {"wayland", "x11"}
WORKER_CLASSES = {"user", "greeter"}


class ConfigurationError(RuntimeError):
    pass


class ProtocolError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeImports:
    message_bus: object
    bus_type: object
    message: object
    message_type: object
    variant: object
    inotify: object
    mask: object


def load_runtime_imports() -> RuntimeImports:
    try:
        from asyncinotify import Inotify, Mask
        from dbus_next import Message, Variant
        from dbus_next.aio import MessageBus
        from dbus_next.constants import BusType, MessageType
    except ModuleNotFoundError as exc:
        package_by_module = {
            "dbus_next": "python3-dbus-next",
            "asyncinotify": "python3-asyncinotify",
        }
        missing = exc.name or "unknown"
        package = package_by_module.get(missing, missing)
        raise ConfigurationError(f"Missing Python module {missing}. Install package {package}.") from exc

    return RuntimeImports(
        message_bus=MessageBus,
        bus_type=BusType,
        message=Message,
        message_type=MessageType,
        variant=Variant,
        inotify=Inotify,
        mask=Mask,
    )


def monotonic_ms() -> int:
    return time.monotonic_ns() // 1_000_000


def wall_timestamp_ms() -> int:
    return time.time_ns() // 1_000_000


def parse_positive_int(name: str, value: str) -> int:
    if not re.fullmatch(r"[0-9]+", value):
        raise ConfigurationError(f"{name} must be a positive integer.")
    parsed = int(value)
    if parsed <= 0:
        raise ConfigurationError(f"{name} must be greater than 0.")
    return parsed


def parse_positive_float(name: str, value: str) -> float:
    if not re.fullmatch(r"[0-9]+([.][0-9]+)?", value):
        raise ConfigurationError(f"{name} must be a positive number.")
    parsed = float(value)
    if parsed <= 0:
        raise ConfigurationError(f"{name} must be greater than 0.")
    return parsed


def validate_state_dir(value: str) -> Path:
    if value != DEFAULT_STATE_DIR:
        raise ConfigurationError(f"STATE_DIR must be {DEFAULT_STATE_DIR}.")
    path = Path(value)
    if path.is_symlink():
        raise ConfigurationError("STATE_DIR must not be a symlink.")
    return path


def validate_device_glob(value: str) -> str:
    if not value.startswith("/sys/class/leds/"):
        raise ConfigurationError("DEVICE_GLOB must point inside /sys/class/leds.")
    if not re.fullmatch(r"/sys/class/leds/[A-Za-z0-9_:.*/+\-]+", value):
        raise ConfigurationError("DEVICE_GLOB contains unsupported characters.")
    if ".." in value:
        raise ConfigurationError("DEVICE_GLOB must not contain '..'.")
    if re.search(r"\s", value):
        raise ConfigurationError("DEVICE_GLOB must not contain whitespace.")
    return value


@dataclass(frozen=True)
class Config:
    seat: str
    timeout_ms: int
    boot_level: int
    poll_interval: float
    state_dir: Path
    device_glob: str

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            seat=os.environ.get("SEAT", "auto"),
            timeout_ms=parse_positive_int("TIMEOUT_MS", os.environ.get("TIMEOUT_MS", "6000")),
            boot_level=parse_positive_int("BOOT_LEVEL", os.environ.get("BOOT_LEVEL", "1")),
            poll_interval=parse_positive_float("POLL_INTERVAL", os.environ.get("POLL_INTERVAL", "10")),
            state_dir=validate_state_dir(os.environ.get("STATE_DIR", DEFAULT_STATE_DIR)),
            device_glob=validate_device_glob(os.environ.get("DEVICE_GLOB", DEFAULT_DEVICE_GLOB)),
        )


@dataclass
class KeyboardDevice:
    path: Path
    decision: BacklightDecision

    @property
    def brightness_path(self) -> Path:
        return self.path / "brightness"

    @property
    def max_brightness_path(self) -> Path:
        return self.path / "max_brightness"

    def read_int(self, path: Path) -> int:
        value = path.read_text(encoding="ascii").strip()
        if not re.fullmatch(r"[0-9]+", value):
            raise RuntimeError(f"Invalid integer in {path}.")
        return int(value)

    def read_level(self) -> int:
        return self.read_int(self.brightness_path)

    def read_max_level(self) -> int:
        value = self.read_int(self.max_brightness_path)
        if value <= 0:
            raise RuntimeError(f"Invalid max_brightness in {self.max_brightness_path}.")
        return value

    def write_level(self, level: int) -> None:
        self.brightness_path.write_text(f"{level}\n", encoding="ascii")


@dataclass(frozen=True)
class SessionInfo:
    session_id: str
    path: str
    uid: int
    seat: str
    session_class: str
    session_type: str
    active: bool
    state: str
    locked: bool

    @property
    def unlocked_user(self) -> bool:
        return self.session_class == "user" and not self.locked


@dataclass(frozen=True)
class RootEvent:
    kind: str
    session_id: str | None = None
    uid: int | None = None
    path: str | None = None
    percent: int | None = None
    source: str | None = None
    request_id: int | None = None
    message: str | None = None
    deadline_ms: int | None = None


class StateStore:
    def __init__(self, state_dir: Path, boot_level: int) -> None:
        self.state_dir = state_dir
        self.default_boot_level = boot_level

    def prepare(self) -> None:
        self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.state_dir.is_symlink():
            raise ConfigurationError(f"State directory must not be a symlink: {self.state_dir}")
        self.state_dir.chmod(0o700)

    def user_file_for_device(self, device: Path, uid: int) -> Path:
        if uid < 0:
            raise ConfigurationError(f"Invalid uid for account state: {uid}")
        return self.state_dir / f"{state_name_for_device(device)}.uid-{uid}.level"

    def load_user_level(self, device: Path, uid: int, max_brightness: int) -> int:
        self.prepare()
        state_file = self.user_file_for_device(device, uid)
        if state_file.is_symlink():
            raise ConfigurationError(f"State file must not be a symlink: {state_file}")
        try:
            value = state_file.read_text(encoding="ascii").strip()
            state_file.chmod(0o600)
        except FileNotFoundError:
            return clamp_boot_level(self.default_boot_level, max_brightness)
        except OSError as exc:
            raise ConfigurationError(f"Cannot read state file {state_file}: {exc}") from exc
        if not re.fullmatch(r"[0-9]+", value):
            return clamp_boot_level(self.default_boot_level, max_brightness)
        return clamp_boot_level(int(value), max_brightness)

    def save_user_level(self, device: Path, uid: int, level: int, max_brightness: int) -> int:
        self.prepare()
        normalized = clamp_boot_level(level, max_brightness)
        state_file = self.user_file_for_device(device, uid)
        if state_file.is_symlink():
            raise ConfigurationError(f"State file must not be a symlink: {state_file}")
        state_file.write_text(f"{normalized}\n", encoding="ascii")
        state_file.chmod(0o600)
        return normalized


def unpack_variant(value: object) -> object:
    if hasattr(value, "value"):
        return unpack_variant(getattr(value, "value"))
    if isinstance(value, tuple):
        return tuple(unpack_variant(item) for item in value)
    if isinstance(value, list):
        return [unpack_variant(item) for item in value]
    if isinstance(value, dict):
        return {str(key): unpack_variant(item) for key, item in value.items()}
    return value


class DBusClient:
    def __init__(self, bus: object, imports: RuntimeImports) -> None:
        self.bus = bus
        self.imports = imports

    async def call(
        self,
        destination: str,
        path: str,
        interface: str,
        member: str,
        signature: str = "",
        body: list[object] | None = None,
        timeout: float = 5.0,
    ) -> list[object]:
        message = self.imports.message(
            destination=destination,
            path=path,
            interface=interface,
            member=member,
            signature=signature,
            body=[] if body is None else body,
        )
        reply = await asyncio.wait_for(self.bus.call(message), timeout)
        if getattr(reply, "message_type") == self.imports.message_type.ERROR:
            error_name = getattr(reply, "error_name", "org.freedesktop.DBus.Error.Failed")
            error_body = getattr(reply, "body", [])
            raise RuntimeError(f"{destination} {interface}.{member} failed: {error_name} {error_body}")
        raw_body = getattr(reply, "body", [])
        if isinstance(raw_body, list):
            return raw_body
        return []

    async def add_match(self, rule: str) -> None:
        await self.call(DBUS_DESTINATION, DBUS_PATH, DBUS_INTERFACE, "AddMatch", "s", [rule])

    async def get_all(self, destination: str, path: str, interface_name: str) -> dict[str, object]:
        body = await self.call(destination, path, PROPERTIES_INTERFACE, "GetAll", "s", [interface_name])
        if not body:
            return {}
        value = unpack_variant(body[0])
        if isinstance(value, dict):
            return value
        return {}

    async def set_int_property(self, destination: str, path: str, interface_name: str, property_name: str, value: int) -> None:
        variant = self.imports.variant("i", value)
        await self.call(destination, path, PROPERTIES_INTERFACE, "Set", "ssv", [interface_name, property_name, variant])


def is_json_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def parse_uid(value: object) -> int:
    if is_json_int(value):
        return value
    if isinstance(value, (tuple, list)) and value and is_json_int(value[0]):
        return value[0]
    return -1


def parse_seat(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (tuple, list)) and value and isinstance(value[0], str):
        return value[0]
    return ""


def parse_str(value: object) -> str:
    if isinstance(value, str):
        return value
    return ""


def parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return False


class WorkerClient:
    def __init__(
        self,
        session: SessionInfo,
        process: asyncio.subprocess.Process,
        queue: asyncio.Queue[RootEvent],
    ) -> None:
        self.session = session
        self.process = process
        self.queue = queue
        self.pending: dict[int, asyncio.Future[JsonObject]] = {}
        self.next_request_id = 1
        self.command_lock = asyncio.Lock()
        self.reader_task: asyncio.Task[None] | None = None
        self.stderr_task: asyncio.Task[None] | None = None

    @classmethod
    async def start(cls, session: SessionInfo, config: Config, queue: asyncio.Queue[RootEvent]) -> "WorkerClient":
        user = pwd.getpwuid(session.uid)
        gid = user.pw_gid
        bus_path = f"/run/user/{session.uid}/bus"
        env = {
            "PATH": os.environ.get("PATH", "/usr/sbin:/usr/bin:/sbin:/bin"),
            "PYTHONUNBUFFERED": "1",
            "XDG_RUNTIME_DIR": f"/run/user/{session.uid}",
            "DBUS_SESSION_BUS_ADDRESS": f"unix:path={bus_path}",
        }
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker",
            "--session-id",
            session.session_id,
            "--uid",
            str(session.uid),
            "--gid",
            str(gid),
            "--timeout-ms",
            str(config.timeout_ms),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            preexec_fn=drop_privileges(session.uid, gid),
        )
        worker = cls(session, process, queue)
        worker.reader_task = asyncio.create_task(worker.read_stdout())
        worker.stderr_task = asyncio.create_task(worker.read_stderr())
        return worker

    async def read_stdout(self) -> None:
        stdout = self.process.stdout
        if stdout is None:
            await self.queue.put(RootEvent("worker_exit", self.session.session_id, self.session.uid, message="missing stdout"))
            return
        try:
            while True:
                line = await stdout.readline()
                if not line:
                    break
                try:
                    decoded: object = json.loads(line.decode("utf-8"))
                    if not isinstance(decoded, dict):
                        raise ProtocolError("worker message is not an object")
                    message = normalize_json_object(decoded)
                    message_type = message.get("type")
                    request_id = message.get("request_id")
                    if is_json_int(request_id):
                        future = self.pending.pop(request_id, None)
                        if future is None:
                            continue
                        if not future.done():
                            if message_type == "event_error":
                                future.set_exception(RuntimeError(str(message.get("message", "worker error"))))
                            else:
                                future.set_result(message)
                        continue
                    await self.queue.put(worker_message_to_event(message))
                except Exception as exc:
                    await self.queue.put(
                        RootEvent("worker_protocol_error", self.session.session_id, self.session.uid, message=str(exc))
                    )
        finally:
            await self.queue.put(RootEvent("worker_exit", self.session.session_id, self.session.uid))

    async def read_stderr(self) -> None:
        stderr = self.process.stderr
        if stderr is None:
            return
        while True:
            line = await stderr.readline()
            if not line:
                return
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                logging.error("GNOME worker session %s stderr: %s", self.session.session_id, text)

    async def send_command(self, command_type: str, payload: JsonObject, timeout: float = 2.0) -> JsonObject:
        async with self.command_lock:
            stdin = self.process.stdin
            if stdin is None:
                raise RuntimeError("worker stdin is not available")
            request_id = self.next_request_id
            self.next_request_id += 1
            message: JsonObject = {
                "type": command_type,
                "session_id": self.session.session_id,
                "uid": self.session.uid,
                "timestamp_ms": wall_timestamp_ms(),
                "request_id": request_id,
            }
            message.update(payload)
            loop = asyncio.get_running_loop()
            future: asyncio.Future[JsonObject] = loop.create_future()
            self.pending[request_id] = future
            try:
                stdin.write((json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8"))
                await stdin.drain()
                return await asyncio.wait_for(future, timeout)
            finally:
                self.pending.pop(request_id, None)

    async def set_brightness(self, percent: int, target_level: int) -> None:
        await self.send_command("cmd_set_brightness", {"percent": percent, "target_level": target_level})

    async def sync_idle_state(self) -> int:
        response = await self.send_command("cmd_sync_idle_state", {})
        idle_ms = response.get("idle_ms")
        if not is_json_int(idle_ms):
            raise ProtocolError("cmd_sync_idle_state returned invalid idle_ms")
        return max(idle_ms, 0)

    async def stop(self) -> None:
        if self.process.returncode is not None:
            return
        try:
            await self.send_command("cmd_stop", {}, timeout=1.0)
        except Exception:
            self.process.terminate()
        try:
            await asyncio.wait_for(self.process.wait(), 2.0)
        except asyncio.TimeoutError:
            self.process.kill()
            await self.process.wait()
        if self.reader_task is not None:
            with suppress(asyncio.CancelledError):
                await self.reader_task
        if self.stderr_task is not None:
            with suppress(asyncio.CancelledError):
                await self.stderr_task


def normalize_json_object(decoded: dict[object, object]) -> JsonObject:
    normalized: JsonObject = {}
    for key, value in decoded.items():
        if not isinstance(key, str):
            continue
        normalized[key] = normalize_json_value(value)
    return normalized


def normalize_json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [normalize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): normalize_json_value(item) for key, item in value.items()}
    return str(value)


def worker_message_to_event(message: JsonObject) -> RootEvent:
    message_type = str(message.get("type", ""))
    session_value = message.get("session_id")
    uid_value = message.get("uid")
    session_id = session_value if isinstance(session_value, str) else None
    uid = uid_value if is_json_int(uid_value) else None
    percent_value = message.get("percent")
    percent = percent_value if is_json_int(percent_value) else None
    source_value = message.get("source")
    source = source_value if isinstance(source_value, str) else None
    message_value = message.get("message")
    text = message_value if isinstance(message_value, str) else None
    return RootEvent(message_type, session_id, uid, percent=percent, source=source, message=text)


def drop_privileges(uid: int, gid: int):
    def apply() -> None:
        os.setgroups([])
        os.setgid(gid)
        os.setuid(uid)

    return apply


class RootDaemon:
    def __init__(self, config: Config, imports: RuntimeImports) -> None:
        self.config = config
        self.imports = imports
        self.state_store = StateStore(config.state_dir, config.boot_level)
        self.devices: dict[str, KeyboardDevice] = {}
        self.sessions: dict[str, SessionInfo] = {}
        self.workers: dict[str, WorkerClient] = {}
        self.queue: asyncio.Queue[RootEvent] = asyncio.Queue()
        self.dbus: DBusClient | None = None
        self.running = True
        self.active_session_id: str | None = None
        self.last_allow_manual_off: bool | None = None
        self.manual_activity_until: dict[int, int] = {}
        self.deferred_idle_deadlines: dict[tuple[str, int], int] = {}
        self.deferred_idle_tasks: set[asyncio.Task[None]] = set()
        self.worker_relevance_messages: dict[str, str] = {}
        self.idle_reconcile_failures: dict[str, str] = {}
        self.session_summary: tuple[str, ...] = ()
        self.inotify_task: asyncio.Task[None] | None = None
        self.reconcile_task: asyncio.Task[None] | None = None

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        for current_signal in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(current_signal, self.request_stop)
        self.refresh_devices(require_devices=True)
        self.state_store.prepare()
        await self.connect_system_bus()
        self.reconcile_task = asyncio.create_task(self.reconcile_loop())
        self.restart_inotify()
        await self.refresh_sessions()
        await self.apply_active_session()
        try:
            while self.running:
                event = await self.queue.get()
                await self.handle_event(event)
        finally:
            self.running = False
            if self.reconcile_task is not None:
                self.reconcile_task.cancel()
            if self.inotify_task is not None:
                self.inotify_task.cancel()
            for task in list(self.deferred_idle_tasks):
                task.cancel()
            await self.stop_workers()
            self.force_boot_levels()

    def request_stop(self) -> None:
        self.running = False
        self.queue.put_nowait(RootEvent("stop"))

    async def connect_system_bus(self) -> None:
        bus_type = getattr(self.imports.bus_type, "SYSTEM")
        bus = await self.imports.message_bus(bus_type=bus_type).connect()
        self.dbus = DBusClient(bus, self.imports)
        await self.dbus.add_match("type='signal',interface='org.freedesktop.login1.Manager',path='/org/freedesktop/login1'")
        await self.dbus.add_match("type='signal',interface='org.freedesktop.login1.Session'")
        await self.dbus.add_match(
            "type='signal',interface='org.freedesktop.DBus.Properties',arg0='org.freedesktop.login1.Session'"
        )
        bus.add_message_handler(self.handle_dbus_message)
        logging.info("Connected logind system bus")

    def handle_dbus_message(self, message: object) -> None:
        if getattr(message, "message_type") != self.imports.message_type.SIGNAL:
            return
        interface = str(getattr(message, "interface", ""))
        member = str(getattr(message, "member", ""))
        path = str(getattr(message, "path", ""))
        if interface == LOGIND_MANAGER_INTERFACE and member in {
            "SessionNew",
            "SessionRemoved",
            "SeatNew",
            "SeatRemoved",
            "PrepareForShutdown",
            "PrepareForSleep",
        }:
            self.queue.put_nowait(RootEvent("logind", path=path, message=member))
        elif interface == LOGIND_SESSION_INTERFACE and member in {"Lock", "Unlock"}:
            self.queue.put_nowait(RootEvent("logind", path=path, message=member))
        elif interface == PROPERTIES_INTERFACE:
            self.queue.put_nowait(RootEvent("logind", path=path, message=member))

    async def handle_event(self, event: RootEvent) -> None:
        if event.kind == "stop":
            return
        if event.kind == "logind":
            if event.message in {"PrepareForShutdown", "PrepareForSleep"}:
                self.force_boot_levels()
            await self.refresh_sessions()
            await self.apply_active_session()
            return
        if event.kind == "sysfs":
            await self.observe_active_session_state()
            return
        if event.kind == "event_idle":
            await self.handle_idle_event(event)
            return
        if event.kind == "deferred_idle":
            await self.handle_deferred_idle_event(event)
            return
        if event.kind == "event_active":
            await self.handle_active_event(event)
            return
        if event.kind == "event_idle_unavailable":
            await self.handle_idle_unavailable_event(event)
            return
        if event.kind == "event_brightness_changed":
            await self.handle_gnome_brightness_event(event)
            return
        if event.kind == "event_ready":
            logging.info("GNOME worker ready for session %s uid %s", event.session_id, event.uid)
            return
        if event.kind == "event_error":
            logging.error("GNOME worker error for session %s uid %s: %s", event.session_id, event.uid, event.message)
            return
        if event.kind == "worker_protocol_error":
            logging.error("Worker protocol error for session %s uid %s: %s", event.session_id, event.uid, event.message)
            return
        if event.kind == "worker_exit":
            await self.handle_worker_exit(event)
            return
        logging.warning("Ignoring unknown event %s", event.kind)

    async def handle_worker_exit(self, event: RootEvent) -> None:
        if event.session_id is None:
            return
        worker = self.workers.get(event.session_id)
        returncode: int | None = None
        if worker is not None:
            returncode = worker.process.returncode
            if returncode is None:
                try:
                    returncode = await asyncio.wait_for(worker.process.wait(), 0.1)
                except asyncio.TimeoutError:
                    return
        self.workers.pop(event.session_id, None)
        session = self.sessions.get(event.session_id)
        if session is not None and self.worker_session_relevant(session):
            logging.warning("GNOME worker exited for active session %s with status %s", event.session_id, returncode)

    def read_max_level_for_path(self, path: Path) -> int:
        max_path = path / "max_brightness"
        value = max_path.read_text(encoding="ascii").strip()
        if not re.fullmatch(r"[0-9]+", value):
            raise RuntimeError(f"Invalid max_brightness in {max_path}.")
        max_level = int(value)
        if max_level <= 0:
            raise RuntimeError(f"Invalid max_brightness in {max_path}.")
        return max_level

    def refresh_devices(self, require_devices: bool = False) -> None:
        found: dict[str, KeyboardDevice] = {}
        for candidate in sorted(glob.glob(self.config.device_glob)):
            path = Path(candidate)
            if not path.is_dir():
                continue
            if not (path / "brightness").is_file() or not (path / "max_brightness").is_file():
                continue
            key = str(path)
            existing = self.devices.get(key)
            if existing is not None:
                found[key] = existing
                continue
            boot = clamp_boot_level(self.config.boot_level, self.read_max_level_for_path(path))
            device = KeyboardDevice(path, BacklightDecision(boot_level=boot, last_nonzero_level=boot))
            found[key] = device
            logging.info("Detected keyboard backlight device %s", key)
        if require_devices and not found:
            raise ConfigurationError(f"No keyboard backlight devices matched {self.config.device_glob}.")
        if set(found) != set(self.devices):
            self.devices = found
            self.restart_inotify()
        else:
            self.devices = found

    def restart_inotify(self) -> None:
        if self.inotify_task is not None:
            self.inotify_task.cancel()
        if self.devices:
            self.inotify_task = asyncio.create_task(self.watch_sysfs())

    async def watch_sysfs(self) -> None:
        mask = self.imports.mask.CLOSE_WRITE | self.imports.mask.MODIFY | self.imports.mask.ATTRIB | self.imports.mask.DELETE_SELF | self.imports.mask.MOVE_SELF
        inotify = self.imports.inotify()
        try:
            for device in self.devices.values():
                inotify.add_watch(device.brightness_path, mask)
            async for event in inotify:
                path = self.path_from_inotify_event(event)
                await self.queue.put(RootEvent("sysfs", path=path))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logging.error("inotify watcher failed: %s", exc)
            await self.queue.put(RootEvent("sysfs", message=str(exc)))
        finally:
            close = getattr(inotify, "close", None)
            if callable(close):
                close()

    def path_from_inotify_event(self, event: object) -> str | None:
        value = getattr(event, "path", None)
        if value is not None:
            return str(value)
        watch = getattr(event, "watch", None)
        if watch is not None:
            watch_path = getattr(watch, "path", None)
            if watch_path is not None:
                return str(watch_path)
        return None

    async def reconcile_loop(self) -> None:
        while self.running:
            await asyncio.sleep(self.config.poll_interval)
            try:
                self.refresh_devices()
                await self.refresh_sessions()
                await self.apply_active_session()
                await self.observe_active_session_state()
                await self.reconcile_idle_state()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logging.error("Reconcile failed: %s", exc)

    async def refresh_sessions(self) -> None:
        if self.dbus is None:
            raise RuntimeError("system bus is not connected")
        body = await self.dbus.call(LOGIND_DESTINATION, LOGIND_MANAGER_PATH, LOGIND_MANAGER_INTERFACE, "ListSessions")
        rows = unpack_variant(body[0]) if body else []
        sessions: dict[str, SessionInfo] = {}
        if isinstance(rows, list):
            for row in rows:
                session = await self.session_from_row(row)
                if session is not None:
                    sessions[session.session_id] = session
        self.sessions = sessions
        summary = tuple(
            sorted(
                f"{session.session_id}:{session.uid}:{session.seat}:{session.session_class}:"
                f"{session.session_type}:{session.active}:{session.locked}"
                for session in self.sessions.values()
            )
        )
        if summary != self.session_summary:
            logging.info("Refreshed %s logind sessions", len(self.sessions))
            self.session_summary = summary
        await self.sync_workers()

    async def session_from_row(self, row: object) -> SessionInfo | None:
        if self.dbus is None or not isinstance(row, (tuple, list)) or not row:
            return None
        session_id = str(row[0])
        path = str(row[4]) if len(row) >= 5 else ""
        if not path:
            path_body = await self.dbus.call(LOGIND_DESTINATION, LOGIND_MANAGER_PATH, LOGIND_MANAGER_INTERFACE, "GetSession", "s", [session_id])
            if not path_body:
                return None
            path = str(path_body[0])
        try:
            properties = await self.dbus.get_all(LOGIND_DESTINATION, path, LOGIND_SESSION_INTERFACE)
        except Exception as exc:
            logging.warning("Cannot read logind session %s: %s", session_id, exc)
            return None
        uid = parse_uid(properties.get("User"))
        if uid < 0:
            uid = int(row[1]) if len(row) > 1 and is_json_int(row[1]) else -1
        return SessionInfo(
            session_id=session_id,
            path=path,
            uid=uid,
            seat=parse_seat(properties.get("Seat")),
            session_class=parse_str(properties.get("Class")),
            session_type=parse_str(properties.get("Type")),
            active=parse_bool(properties.get("Active")),
            state=parse_str(properties.get("State")),
            locked=parse_bool(properties.get("LockedHint")),
        )

    async def sync_workers(self) -> None:
        relevant: dict[str, SessionInfo] = {}
        for session_id, session in self.sessions.items():
            reason = self.worker_skip_reason(session)
            if reason is None:
                relevant[session_id] = session
                message = (
                    f"worker relevant: uid={session.uid} seat={session.seat} "
                    f"class={session.session_class} type={session.session_type}"
                )
            else:
                message = (
                    f"worker skipped: {reason}; uid={session.uid} seat={session.seat} "
                    f"class={session.session_class} type={session.session_type} active={session.active}"
                )
            if self.worker_relevance_messages.get(session_id) != message:
                logging.info("Session %s %s", session_id, message)
                self.worker_relevance_messages[session_id] = message
        for session_id in list(self.workers):
            if session_id not in relevant:
                worker = self.workers.pop(session_id)
                self.idle_reconcile_failures.pop(session_id, None)
                await worker.stop()
        for session_id, session in relevant.items():
            if session_id in self.workers:
                continue
            try:
                logging.info("Starting GNOME worker for session %s uid %s", session.session_id, session.uid)
                self.workers[session_id] = await WorkerClient.start(session, self.config, self.queue)
            except Exception as exc:
                logging.error("Cannot start GNOME worker for session %s uid %s: %s", session.session_id, session.uid, exc)

    def worker_session_relevant(self, session: SessionInfo) -> bool:
        return self.worker_skip_reason(session) is None

    def worker_skip_reason(self, session: SessionInfo) -> str | None:
        if not session.active:
            return "inactive"
        if not self.seat_matches(session):
            return "seat mismatch"
        if session.session_class not in WORKER_CLASSES:
            return "unsupported session class"
        if session.uid < 0:
            return "missing uid"
        return None

    def seat_matches(self, session: SessionInfo) -> bool:
        if self.config.seat == "auto":
            return bool(session.seat)
        return session.seat == self.config.seat

    def selected_active_session(self) -> SessionInfo | None:
        candidates = [session for session in self.sessions.values() if session.active and self.seat_matches(session)]
        if not candidates:
            return None
        for session in candidates:
            if session.session_class == "user" and session.session_type in GRAPHICAL_SESSION_TYPES:
                return session
        for session in candidates:
            if session.session_class == "user":
                return session
        for session in candidates:
            if session.session_class in WORKER_CLASSES:
                return session
        return candidates[0]

    async def apply_active_session(self) -> None:
        session = self.selected_active_session()
        if session is None or session.uid < 0:
            if self.active_session_id is not None:
                logging.info("No active session, restoring boot brightness")
            self.active_session_id = None
            self.last_allow_manual_off = None
            self.force_boot_levels()
            return
        allow_manual_off = session.unlocked_user
        if self.active_session_id == session.session_id and self.last_allow_manual_off == allow_manual_off:
            return
        if allow_manual_off:
            self.manual_activity_until_ms_for_uid(session.uid, monotonic_ms() + self.config.timeout_ms)
            for device in self.devices.values():
                device.decision.seen_levels.setdefault(session.uid, device.read_level())
        await self.activate_session(session, allow_manual_off)
        self.active_session_id = session.session_id
        self.last_allow_manual_off = allow_manual_off

    def manual_activity_until_ms_for_uid(self, uid: int, deadline: int | None = None) -> int:
        if deadline is not None:
            self.manual_activity_until[uid] = deadline
        return self.manual_activity_until.get(uid, 0)

    async def activate_session(self, session: SessionInfo, allow_manual_off: bool) -> None:
        for device in self.devices.values():
            if allow_manual_off and session.uid not in device.decision.desired_levels:
                saved = self.state_store.load_user_level(device.path, session.uid, device.read_max_level())
                device.decision.remember_visible_level(session.uid, saved)
            target = device.decision.activation_level(session.uid, allow_manual_off)
            if target is not None:
                await self.write_level(session, device, target)
            current = device.read_level()
            device.decision.finish_activation(session.uid, current, allow_manual_off)

    async def observe_active_session_state(self) -> None:
        session = self.selected_active_session()
        if session is None or session.uid < 0:
            return
        if not session.unlocked_user:
            return
        for device in self.devices.values():
            current = device.read_level()
            result = device.decision.observe(
                session.uid,
                current,
                session.unlocked_user,
            )
            await self.apply_observation_result(session, device, result)
        self.update_account_levels_for_session(session)

    async def apply_observation_result(self, session: SessionInfo, device: KeyboardDevice, result: ObservationResult) -> None:
        if result.manual_change:
            self.manual_activity_until_ms_for_uid(session.uid, monotonic_ms() + self.config.timeout_ms)

    async def handle_idle_event(self, event: RootEvent) -> None:
        session = self.session_for_event(event)
        if session is None:
            return
        if not session.unlocked_user:
            return
        manual_deadline = self.manual_activity_until_ms_for_uid(session.uid)
        if manual_deadline > monotonic_ms():
            self.schedule_deferred_idle(session, manual_deadline)
            return
        self.clear_deferred_idle(session)
        await self.dim_session_for_idle(session)

    async def handle_deferred_idle_event(self, event: RootEvent) -> None:
        session = self.session_for_event(event)
        if session is None or event.deadline_ms is None:
            return
        if not session.unlocked_user:
            return
        key = self.deferred_idle_key(session)
        if self.deferred_idle_deadlines.get(key) != event.deadline_ms:
            return
        manual_deadline = self.manual_activity_until_ms_for_uid(session.uid)
        if manual_deadline > monotonic_ms():
            self.schedule_deferred_idle(session, manual_deadline)
            return
        self.deferred_idle_deadlines.pop(key, None)
        await self.dim_session_for_idle(session)

    async def dim_session_for_idle(self, session: SessionInfo) -> None:
        for device in self.devices.values():
            target = device.decision.idle_transition(session.uid, device.read_level())
            if target is not None:
                await self.write_level(session, device, target)

    async def handle_active_event(self, event: RootEvent) -> None:
        session = self.session_for_event(event)
        if session is None:
            return
        if not session.unlocked_user:
            return
        self.clear_deferred_idle(session)
        await self.restore_session_for_activity(session)

    async def handle_idle_unavailable_event(self, event: RootEvent) -> None:
        session = self.session_for_event(event)
        if session is None:
            return
        if event.message:
            logging.warning("GNOME idle unavailable for session %s uid %s: %s", session.session_id, session.uid, event.message)
        self.clear_deferred_idle(session)
        if not session.unlocked_user:
            return
        await self.restore_session_for_activity(session)

    async def restore_session_for_activity(self, session: SessionInfo) -> None:
        for device in self.devices.values():
            target = device.decision.activity_transition(session.uid, device.read_level(), session.unlocked_user)
            if target is not None:
                await self.write_level(session, device, target)
        if session.unlocked_user:
            self.update_account_levels_for_session(session)

    async def reconcile_idle_state(self) -> None:
        session = self.selected_active_session()
        if session is None or session.uid < 0 or not session.unlocked_user:
            return
        worker = self.workers.get(session.session_id)
        if worker is None:
            return
        try:
            idle_ms = await worker.sync_idle_state()
        except Exception as exc:
            message = str(exc)
            if self.idle_reconcile_failures.get(session.session_id) != message:
                logging.warning("GNOME idle reconcile failed for session %s uid %s: %s", session.session_id, session.uid, message)
                self.idle_reconcile_failures[session.session_id] = message
            return
        if session.session_id in self.idle_reconcile_failures:
            logging.info("GNOME idle reconcile recovered for session %s uid %s", session.session_id, session.uid)
            self.idle_reconcile_failures.pop(session.session_id, None)
        if idle_ms >= self.config.timeout_ms:
            await self.handle_idle_event(RootEvent("event_idle", session.session_id, session.uid))
            return
        if self.session_needs_activity_restore(session):
            await self.handle_active_event(RootEvent("event_active", session.session_id, session.uid))

    def session_needs_activity_restore(self, session: SessionInfo) -> bool:
        if self.deferred_idle_key(session) in self.deferred_idle_deadlines:
            return True
        return any(device.decision.dimmed_flags.get(session.uid, False) for device in self.devices.values())

    def deferred_idle_key(self, session: SessionInfo) -> tuple[str, int]:
        return (session.session_id, session.uid)

    def clear_deferred_idle(self, session: SessionInfo) -> None:
        self.deferred_idle_deadlines.pop(self.deferred_idle_key(session), None)

    def schedule_deferred_idle(self, session: SessionInfo, deadline_ms: int) -> None:
        key = self.deferred_idle_key(session)
        if self.deferred_idle_deadlines.get(key) == deadline_ms:
            return
        self.deferred_idle_deadlines[key] = deadline_ms
        task = asyncio.create_task(self.emit_deferred_idle(session.session_id, session.uid, deadline_ms))
        self.deferred_idle_tasks.add(task)
        task.add_done_callback(self.deferred_idle_tasks.discard)

    async def emit_deferred_idle(self, session_id: str, uid: int, deadline_ms: int) -> None:
        await asyncio.sleep(max(0, deadline_ms - monotonic_ms()) / 1000)
        await self.queue.put(RootEvent("deferred_idle", session_id, uid, deadline_ms=deadline_ms))

    async def handle_gnome_brightness_event(self, event: RootEvent) -> None:
        session = self.session_for_event(event)
        if session is None or event.percent is None:
            return
        if not session.unlocked_user:
            return
        for device in self.devices.values():
            target = percent_to_level(event.percent, device.read_max_level())
            managed = device.decision.managed_level_for_uid(session.uid)
            if managed != target:
                result = device.decision.accept_external_level(
                    session.uid,
                    target,
                    session.unlocked_user,
                    True,
                )
                await self.apply_observation_result(session, device, result)
            if device.read_level() != target:
                device.write_level(target)
                device.decision.set_managed_level(session.uid, target)
        self.update_account_levels_for_session(session)

    def session_for_event(self, event: RootEvent) -> SessionInfo | None:
        if event.session_id is None or event.uid is None:
            return None
        session = self.sessions.get(event.session_id)
        if session is None:
            return None
        if session.uid != event.uid:
            return None
        if self.active_session_id != session.session_id:
            return None
        return session

    async def write_level(self, session: SessionInfo | None, device: KeyboardDevice, requested: int) -> None:
        max_level = device.read_max_level()
        target = clamp_level(requested, max_level)
        if session is not None:
            worker = self.workers.get(session.session_id)
            if worker is not None:
                percent = level_to_percent(target, max_level)
                try:
                    await worker.set_brightness(percent, target)
                    actual = device.read_level()
                    if actual == target:
                        device.decision.set_managed_level(session.uid, actual)
                        return
                    logging.warning(
                        "GNOME brightness write for %s returned sysfs level %s instead of %s",
                        device.path,
                        actual,
                        target,
                    )
                except Exception as exc:
                    logging.warning("GNOME brightness write failed for session %s: %s", session.session_id, exc)
        current = device.read_level()
        if current != target:
            device.write_level(target)
        if session is not None:
            device.decision.set_managed_level(session.uid, target)
            worker = self.workers.get(session.session_id)
            if worker is not None:
                try:
                    await worker.set_brightness(level_to_percent(target, max_level), target)
                except Exception as exc:
                    logging.warning("GNOME brightness resync failed for session %s: %s", session.session_id, exc)

    def save_account_level(self, device: KeyboardDevice, uid: int, level: int) -> None:
        saved = self.state_store.save_user_level(device.path, uid, level, device.read_max_level())
        device.decision.remember_visible_level(uid, saved)

    def update_account_levels_for_session(self, session: SessionInfo) -> None:
        for device in self.devices.values():
            candidate = device.decision.boot_candidate_for_uid(session.uid, device.read_level())
            self.save_account_level(device, session.uid, candidate)

    def force_boot_levels(self) -> None:
        for device in self.devices.values():
            max_level = device.read_max_level()
            target = clamp_boot_level(device.decision.boot_level, max_level)
            try:
                if device.read_level() != target:
                    device.write_level(target)
            except OSError as exc:
                logging.error("Cannot restore boot brightness for %s: %s", device.path, exc)

    async def stop_workers(self) -> None:
        for session_id in list(self.workers):
            worker = self.workers.pop(session_id)
            await worker.stop()


class UserWorker:
    def __init__(self, session_id: str, uid: int, timeout_ms: int, imports: RuntimeImports) -> None:
        self.session_id = session_id
        self.uid = uid
        self.timeout_ms = timeout_ms
        self.imports = imports
        self.dbus: DBusClient | None = None
        self.running = True
        self.idle_watch_id: int | None = None
        self.active_watch_id: int | None = None

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        for current_signal in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(current_signal, self.request_stop)
        address = os.environ.get("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{self.uid}/bus")
        bus = await self.imports.message_bus(bus_address=address).connect()
        self.dbus = DBusClient(bus, self.imports)
        await self.dbus.add_match("type='signal',interface='org.gnome.Mutter.IdleMonitor',member='WatchFired'")
        await self.dbus.add_match(
            "type='signal',interface='org.gnome.SettingsDaemon.Power.Keyboard',member='BrightnessChanged'"
        )
        bus.add_message_handler(self.handle_dbus_message)
        await self.arm_initial_idle_watch()
        self.emit({"type": "event_ready"})
        await self.command_loop()

    def request_stop(self) -> None:
        self.running = False
        try:
            os.close(sys.stdin.fileno())
        except OSError:
            pass

    async def arm_initial_idle_watch(self) -> None:
        if self.dbus is None:
            return
        try:
            idle_ms = await self.read_idle_ms()
            if idle_ms >= self.timeout_ms:
                self.emit({"type": "event_idle"})
                self.active_watch_id = await self.add_active_watch()
            else:
                self.idle_watch_id = await self.add_idle_watch()
        except Exception as exc:
            self.emit({"type": "event_idle_unavailable", "message": f"Cannot read GNOME idle time: {exc}"})

    async def add_idle_watch(self) -> int:
        if self.dbus is None:
            raise RuntimeError("session bus is not connected")
        body = await self.dbus.call(MUTTER_DESTINATION, MUTTER_PATH, MUTTER_INTERFACE, "AddIdleWatch", "t", [self.timeout_ms])
        return int(unpack_variant(body[0]))

    async def add_active_watch(self) -> int:
        if self.dbus is None:
            raise RuntimeError("session bus is not connected")
        body = await self.dbus.call(MUTTER_DESTINATION, MUTTER_PATH, MUTTER_INTERFACE, "AddUserActiveWatch")
        return int(unpack_variant(body[0]))

    async def read_idle_ms(self) -> int:
        if self.dbus is None:
            raise RuntimeError("session bus is not connected")
        body = await self.dbus.call(MUTTER_DESTINATION, MUTTER_PATH, MUTTER_INTERFACE, "GetIdletime")
        idle_ms = int(unpack_variant(body[0])) if body else 0
        return max(idle_ms, 0)

    async def sync_idle_state(self) -> int:
        idle_ms = await self.read_idle_ms()
        if idle_ms >= self.timeout_ms:
            if self.active_watch_id is None:
                self.idle_watch_id = None
                self.active_watch_id = await self.add_active_watch()
            return idle_ms
        if self.idle_watch_id is None:
            self.active_watch_id = None
            self.idle_watch_id = await self.add_idle_watch()
        return idle_ms

    def handle_dbus_message(self, message: object) -> None:
        if getattr(message, "message_type") != self.imports.message_type.SIGNAL:
            return
        interface = str(getattr(message, "interface", ""))
        member = str(getattr(message, "member", ""))
        body = unpack_variant(getattr(message, "body", []))
        if interface == MUTTER_INTERFACE and member == "WatchFired":
            asyncio.create_task(self.handle_watch_fired(body))
        elif interface == POWER_KEYBOARD_INTERFACE and member == "BrightnessChanged":
            self.handle_brightness_changed(body)

    async def handle_watch_fired(self, body: object) -> None:
        if not isinstance(body, list) or not body:
            return
        watch_id = int(body[0])
        if self.idle_watch_id == watch_id:
            self.idle_watch_id = None
            self.emit({"type": "event_idle"})
            try:
                self.active_watch_id = await self.add_active_watch()
            except Exception as exc:
                self.emit({"type": "event_idle_unavailable", "message": f"Cannot add active watch: {exc}"})
        elif self.active_watch_id == watch_id:
            self.active_watch_id = None
            self.emit({"type": "event_active"})
            try:
                self.idle_watch_id = await self.add_idle_watch()
            except Exception as exc:
                self.emit({"type": "event_idle_unavailable", "message": f"Cannot add idle watch: {exc}"})

    def handle_brightness_changed(self, body: object) -> None:
        if not isinstance(body, list) or len(body) < 2:
            return
        brightness = body[0]
        source = body[1]
        if not is_json_int(brightness):
            return
        self.emit(
            {
                "type": "event_brightness_changed",
                "percent": clamp_percent(brightness),
                "source": source if isinstance(source, str) else "",
            }
        )

    async def command_loop(self) -> None:
        while self.running:
            line = await asyncio.to_thread(sys.stdin.readline)
            if not line:
                break
            try:
                decoded: object = json.loads(line)
                if not isinstance(decoded, dict):
                    raise ProtocolError("command is not an object")
                message = normalize_json_object(decoded)
                await self.handle_command(message)
            except Exception as exc:
                self.emit({"type": "event_error", "message": str(exc)})

    async def handle_command(self, message: JsonObject) -> None:
        command_type = message.get("type")
        request_id = message.get("request_id")
        if command_type == "cmd_stop":
            self.emit({"type": "event_stopped", "request_id": request_id})
            self.running = False
            return
        if command_type == "cmd_sync_idle_state":
            idle_ms = await self.sync_idle_state()
            self.emit({"type": "event_idle_state", "request_id": request_id, "idle_ms": idle_ms})
            return
        if command_type != "cmd_set_brightness":
            raise ProtocolError(f"unknown command {command_type}")
        percent_value = message.get("percent")
        if not is_json_int(percent_value):
            raise ProtocolError("cmd_set_brightness requires integer percent")
        if self.dbus is None:
            raise RuntimeError("session bus is not connected")
        await self.dbus.set_int_property(
            POWER_DESTINATION,
            POWER_PATH,
            POWER_KEYBOARD_INTERFACE,
            "Brightness",
            clamp_percent(percent_value),
        )
        self.emit({"type": "event_set_complete", "request_id": request_id, "percent": clamp_percent(percent_value)})

    def emit(self, payload: JsonObject) -> None:
        message: JsonObject = {
            "type": str(payload.get("type", "event_error")),
            "session_id": self.session_id,
            "uid": self.uid,
            "timestamp_ms": wall_timestamp_ms(),
        }
        for key, value in payload.items():
            message[key] = value
        sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
        sys.stdout.flush()


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--session-id", default="")
    parser.add_argument("--uid", type=int, default=-1)
    parser.add_argument("--gid", type=int, default=-1)
    parser.add_argument("--timeout-ms", type=int, default=6000)
    return parser.parse_args()


async def async_main() -> int:
    configure_logging()
    args = parse_args()
    imports = load_runtime_imports()
    if args.worker:
        if not args.session_id or args.uid < 0:
            raise ConfigurationError("Worker requires session id and uid.")
        worker = UserWorker(args.session_id, args.uid, args.timeout_ms, imports)
        await worker.run()
        return 0
    config = Config.from_env()
    daemon = RootDaemon(config, imports)
    await daemon.run()
    return 0


def main() -> int:
    try:
        return asyncio.run(async_main())
    except ConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
