from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import logging
import mimetypes
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

# Resolve sibling repositories by absolute path so imports do not depend on cwd.
SCRIPT_DIR = Path(__file__).resolve().parent
HAL_DIR = SCRIPT_DIR.parent / "hal"
MESSAGE_MD_DIR = SCRIPT_DIR.parent / "message_md"

if str(HAL_DIR) not in sys.path:
    sys.path.insert(0, str(HAL_DIR))
if str(MESSAGE_MD_DIR) not in sys.path:
    sys.path.insert(0, str(MESSAGE_MD_DIR))

import config
import markdown
import message_md

try:
    from pywinauto import Application, Desktop
    from pywinauto.keyboard import send_keys
except Exception:  # pragma: no cover - optional dependency
    Application = None
    Desktop = None
    send_keys = None

try:
    import pyautogui
except Exception:  # pragma: no cover - optional dependency
    pyautogui = None

try:
    import pytesseract
    from PIL import ImageGrab
except Exception:  # pragma: no cover - optional dependency
    pytesseract = None
    ImageGrab = None


IS_WINDOWS = os.name == "nt"


# Make this process DPI-aware BEFORE any window measuring or mouse clicking. If
# it is not, Windows virtualizes coordinates under display scaling (e.g. 125% or
# 150%), so pywinauto's window rectangle (physical pixels) and pyautogui's click
# coordinates (logical pixels) disagree - and clicks computed from the rectangle
# land in the wrong pane (often the LEFT conversation list, switching chats).
if IS_WINDOWS:
    try:
        import ctypes as _ctypes_dpi

        # PROCESS_PER_MONITOR_DPI_AWARE = 2 (Win 8.1+); fall back to system-DPI.
        try:
            _ctypes_dpi.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            _ctypes_dpi.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


# --- Win32 SendInput with hardware scan codes ------------------------------
# Chromium/Electron apps (like Signal Desktop) frequently ignore synthetic key
# events that carry only a virtual-key code (which is what pyautogui sends).
# Sending the hardware scan code via SendInput makes the keystrokes look like a
# real keyboard, so multi-modifier shortcuts such as Ctrl+Shift+M register.
if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32

    _VK_MAP = {
        "ctrl": 0x11, "control": 0x11,
        "shift": 0x10,
        "alt": 0x12, "menu": 0x12,
        "win": 0x5B,
        "enter": 0x0D, "return": 0x0D,
        "tab": 0x09,
        "esc": 0x1B, "escape": 0x1B,
        "space": 0x20,
        "backspace": 0x08,
        "home": 0x24, "end": 0x23,
        "pageup": 0x21, "pgup": 0x21,
        "pagedown": 0x22, "pgdn": 0x22,
        "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
        "delete": 0x2E, "del": 0x2E,
        "f10": 0x79,
    }

    # Keys that require the KEYEVENTF_EXTENDEDKEY flag.
    _EXTENDED_VKS = {0x25, 0x26, 0x27, 0x28, 0x2E, 0x24, 0x23, 0x21, 0x22, 0x5B}

    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_SCANCODE = 0x0008
    KEYEVENTF_EXTENDEDKEY = 0x0001
    INPUT_KEYBOARD = 1
    MAPVK_VK_TO_VSC = 0

    ULONG_PTR = ctypes.POINTER(ctypes.c_ulong)

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT)]

    class _INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]

    def _vk_for(name: str) -> int | None:
        key = name.strip().lower()
        if key in _VK_MAP:
            return _VK_MAP[key]
        if len(key) == 1:
            # Letters and digits map to their uppercase ASCII virtual-key code.
            return ord(key.upper())
        return None

    def _make_key_event(vk: int, key_up: bool) -> _INPUT:
        scan = _user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
        flags = KEYEVENTF_SCANCODE
        if vk in _EXTENDED_VKS:
            flags |= KEYEVENTF_EXTENDEDKEY
        if key_up:
            flags |= KEYEVENTF_KEYUP
        ki = _KEYBDINPUT(wVk=0, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=None)
        return _INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=ki))

    def _send_one_input(event: "_INPUT") -> int:
        array = (_INPUT * 1)(event)
        return _user32.SendInput(1, array, ctypes.sizeof(_INPUT))

    def send_scancode_shortcut(keys: list[str], key_delay: float = 0.03) -> bool:
        vks = [_vk_for(k) for k in keys]
        if any(vk is None for vk in vks):
            return False

        # Send each key event as its own SendInput with a small settle delay
        # instead of one atomic batch. Batching all press/release events with zero
        # time between them makes Chromium/Electron (Signal) occasionally miss that
        # a modifier was held when the main key arrives - which silently breaks
        # MULTI-modifier combos like Ctrl+Shift+M (it degrades to Ctrl+M and the
        # media tab never opens) while single-modifier combos (Ctrl+A/C/J) still
        # work. Pressing modifiers first, letting them settle, then the key - the
        # way a real keyboard does - makes Ctrl+Shift+M register reliably.
        ok = True
        for vk in vks:  # press in order: modifiers first, main key last
            if _send_one_input(_make_key_event(vk, False)) != 1:
                ok = False
            time.sleep(key_delay)
        for vk in reversed(vks):  # release in reverse order
            if _send_one_input(_make_key_event(vk, True)) != 1:
                ok = False
            time.sleep(key_delay)
        return ok
else:  # pragma: no cover - non-Windows fallback
    def send_scancode_shortcut(keys: list[str]) -> bool:
        return False


WIKILINK_RE = re.compile(r'(!?)\[\[([^\]|]+)(?:\|([^\]]+))?\]\]')


@dataclass
class AutomationSettings:
    signal_exe: str = ""
    window_title: str = "Signal"
    conversation_search_shortcut: list[str] = field(default_factory=lambda: ["ctrl", "k"])
    save_shortcut: list[str] = field(default_factory=lambda: ["ctrl", "shift", "s"])
    next_item_shortcut: list[str] = field(default_factory=lambda: ["pagedown"])
    downloads_root: str = ""
    state_file: str = ""
    log_file: str = ""
    stop_on_error: bool = False
    dry_run: bool = False
    use_ocr: bool = False
    attachment_wait_seconds: float = 10.0
    poll_interval_seconds: float = 0.25
    max_attachments_per_conversation: int = 9999
    scan_order: str = "shortcut-first"
    max_conversations: int = 200
    startup_wait_seconds: float = 8.0
    allow_search_fallback: bool = False
    download_action_timeout_seconds: float = 8.0
    allow_text_fallback_scan: bool = False
    allow_config_fallback: bool = False
    shortcut_slots: int = 9
    context_menu_right_nudge_px: int = 10
    require_visible_mouse: bool = True
    mouse_move_duration_seconds: float = 0.15
    me: str = ""
    menu_key_delay_seconds: float = 0.6


@dataclass
class MediaRecord:
    slug: str
    label: str
    media_kind: str
    source_label: str
    saved_filename: str
    saved_path: str
    markdown_target: str
    timestamp: str = ""


class AutomationState:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, Any] = {
            "completed": [],
            "failed": [],
            "downloads": [],
            "updated_at": None,
        }

    def load(self) -> None:
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))

    def save(self) -> None:
        self.data["updated_at"] = datetime.now().isoformat(timespec="seconds")
        if self.path.exists() and self.path.is_dir():
            self.path = self.path / "signal_ui_state.json"

        parent = self.path.parent
        if parent.exists() and not parent.is_dir():
            raise RuntimeError(f"State file parent is not a directory: {parent}")

        try:
            parent.mkdir(parents=True, exist_ok=True)
        except FileExistsError as exc:
            raise RuntimeError(f"Could not create state directory: {parent}") from exc

        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")

    def mark_completed(self, slug: str) -> None:
        completed = self.data.setdefault("completed", [])
        if slug not in completed:
            completed.append(slug)

    def mark_failed(self, slug: str, error: str) -> None:
        self.data.setdefault("failed", []).append({"slug": slug, "error": error})

    def add_download(self, record: MediaRecord) -> None:
        self.data.setdefault("downloads", []).append(dataclasses.asdict(record))


def _is_default_arg(args: argparse.Namespace, name: str) -> bool:
    defaults = {
        "config_dir": "",
        "source_folder": "",
        "messages_file": "messages.csv",
        "output_folder": "",
        "me": "",
        "begin": "1900-01-01",
        "signal_exe": "",
        "window_title": "Signal",
        "downloads_root": "",
        "state_file": "",
        "log_file": "",
        "save_shortcut": "ctrl+shift+s",
        "next_item_shortcut": "pagedown",
        "targets": "",
    }
    return getattr(args, name) == defaults.get(name)


def _set_if_default(args: argparse.Namespace, name: str, value: Any) -> None:
    if value is None:
        return
    if _is_default_arg(args, name):
        setattr(args, name, value)


def infer_from_signal_sh(args: argparse.Namespace) -> argparse.Namespace:
    signal_sh = SCRIPT_DIR / "signal.sh"
    if not signal_sh.exists():
        return args

    try:
        content = signal_sh.read_text(encoding="utf-8")
    except Exception:
        return args

    def get_var(name: str) -> str | None:
        match = re.search(rf"^\s*{re.escape(name)}\s*=\s*(.+?)\s*$", content, flags=re.MULTILINE)
        if not match:
            return None
        value = match.group(1).strip().strip('"').strip("'")
        return value or None

    config_dir = get_var("CONFIG_DIR")
    data_dir = get_var("DATA_DIR")
    me = get_var("ME")
    output_dir = get_var("OUTPUT_DIR")

    if config_dir and Path(config_dir).exists():
        _set_if_default(args, "config_dir", config_dir)
    if data_dir and Path(data_dir).exists():
        _set_if_default(args, "source_folder", data_dir)
    if me:
        _set_if_default(args, "me", me)
    if output_dir and Path(output_dir).exists():
        _set_if_default(args, "output_folder", output_dir)
        _set_if_default(args, "downloads_root", output_dir)

    return args


def infer_common_defaults(args: argparse.Namespace) -> argparse.Namespace:
    if _is_default_arg(args, "config_dir"):
        candidates = [
            Path.cwd() / "config",
            SCRIPT_DIR / "config",
            SCRIPT_DIR.parent / "dev-output" / "config",
            Path.cwd(),
        ]
        for candidate in candidates:
            if (candidate / "people.json").exists() and (candidate / "groups.json").exists():
                args.config_dir = str(candidate)
                break

    if _is_default_arg(args, "output_folder"):
        candidates = [Path.cwd(), SCRIPT_DIR.parent / "dev-output"]
        for candidate in candidates:
            if candidate.exists():
                args.output_folder = str(candidate)
                break

    if _is_default_arg(args, "downloads_root") and not _is_default_arg(args, "output_folder"):
        args.downloads_root = args.output_folder

    return args


def apply_json_config(args: argparse.Namespace) -> argparse.Namespace:
    config_path = Path(args.automation_config)
    if not config_path.is_absolute():
        config_path = SCRIPT_DIR / config_path

    if not config_path.exists():
        return args

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    md = payload.get("message_md", payload)
    ui = payload.get("automation", payload)

    _set_if_default(args, "config_dir", md.get("config_dir") or md.get("config-dir"))
    _set_if_default(args, "source_folder", md.get("source_folder") or md.get("source-folder"))
    _set_if_default(args, "messages_file", md.get("messages_file") or md.get("messages-file"))
    _set_if_default(args, "output_folder", md.get("output_folder") or md.get("output-folder"))
    _set_if_default(args, "me", md.get("me") or md.get("my_slug") or md.get("my-slug"))
    _set_if_default(args, "begin", md.get("begin") or md.get("start_date") or md.get("start-date"))

    _set_if_default(args, "signal_exe", ui.get("signal_exe") or ui.get("signal-exe"))
    _set_if_default(args, "window_title", ui.get("window_title") or ui.get("window-title"))
    _set_if_default(args, "downloads_root", ui.get("downloads_root") or ui.get("downloads-root"))
    _set_if_default(args, "state_file", ui.get("state_file") or ui.get("state-file"))
    _set_if_default(args, "log_file", ui.get("log_file") or ui.get("log-file"))
    _set_if_default(args, "save_shortcut", ui.get("save_shortcut") or ui.get("save-shortcut"))
    _set_if_default(args, "next_item_shortcut", ui.get("next_item_shortcut") or ui.get("next-item-shortcut"))
    _set_if_default(args, "targets", ui.get("targets"))

    return args


def parse_shortcut(value: str | list[str]) -> list[str]:
    if isinstance(value, list):
        return value
    return [part.strip() for part in value.split('+') if part.strip()]


def normalize_text(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def is_probable_conversation_title(value: str) -> bool:
    text = (value or "").strip()
    norm = normalize_text(text)
    if not norm:
        return False

    # Filter obvious UI labels.
    if norm in {
        "signal",
        "new message",
        "search",
        "settings",
        "calls",
        "contacts",
        "chats",
        "download",
        "more",
        "menu",
        # Conversation-header buttons/labels that the UIA fallback can pick up
        # instead of the real name (observed: "More actions" leaking through and
        # even tripping the end-of-list detection).
        "more actions",
        "more options",
        "more info",
        "conversation details",
        "contact details",
        "group details",
        "start video call",
        "start voice call",
        "video call",
        "voice call",
        "call",
        "back",
        "close",
        "mute",
        "unmute",
        "search in conversation",
        "show conversation details",
        "view all media",
        "all media",
    }:
        return False

    # Drop likely message preview lines and long sentence-like content.
    if len(text) > 48:
        return False
    if re.search(r"\d{1,2}:\d{2}\s?(am|pm)?", norm):
        return False
    if any(token in norm for token in [" i ", " you ", " he ", " she ", " we ", " they ", " trying ", " worked "]):
        return False
    if text.count(" ") > 5:
        return False

    return True


# Signal Desktop wraps the contact/group name in Unicode directional isolate
# characters: U+2068 (FIRST STRONG ISOLATE) ... U+2069 (POP DIRECTIONAL ISOLATE).
_ISOLATE_RE = re.compile("\u2068(.*?)\u2069", re.DOTALL)

# Words that appear on the conversation header line right after the name.
_HEADER_MARKERS = (
    "not verified",
    "verified",
    "groups in common",
    "group in common",
    "member",
    "members",
)


def parse_conversation_name_from_clipboard(text: str) -> str:
    """Extract the conversation (contact/group) name from copied conversation text.

    When you open a conversation, select all (Ctrl+A) and copy (Ctrl+C), the top
    of the copied text contains the header, e.g.:

        Sun, Jun 28

        \u2068Matthew Pintar\u2069   Name not verified No groups in common

    The name is wrapped in U+2068/U+2069 isolate characters. Prefer an
    isolate-wrapped name that sits on a header line (one that also contains a
    marker such as "Name not verified" or "No groups in common"); otherwise fall
    back to the first isolate-wrapped segment.
    """
    if not text:
        return ""

    matches = list(_ISOLATE_RE.finditer(text))

    # Prefer an isolate-wrapped name on a recognizable header line.
    for m in matches:
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.end())
        if line_end == -1:
            line_end = len(text)
        line = text[line_start:line_end].lower()
        if any(marker in line for marker in _HEADER_MARKERS):
            name = m.group(1).strip()
            if name:
                return name

    # Otherwise, take the first isolate-wrapped segment.
    if matches:
        name = matches[0].group(1).strip()
        if name:
            return name

    # Fallback: no isolate markers. Scan for a header-marker line and take the
    # text preceding the first marker.
    for raw_line in text.splitlines():
        low = raw_line.lower()
        for marker in _HEADER_MARKERS:
            idx = low.find(marker)
            if idx > 0:
                candidate = raw_line[:idx].strip(" \t\u2068\u2069")
                if candidate:
                    return candidate

    return ""


def build_target_aliases(target: Any) -> list[str]:
    aliases: list[str] = []

    slug = getattr(target, "slug", "") or ""
    identity = getattr(target, "identity", None)
    full_name = getattr(identity, "full_name", "") if identity else ""
    identity_first = getattr(identity, "first_name", "") if identity else ""

    # People carry first-name/last-name directly (from people.json). Match the
    # Signal header against the first name alone AND against "First Last".
    person_first = getattr(target, "first_name", "") or ""
    person_last = getattr(target, "last_name", "") or ""
    person_full = (person_first + " " + person_last).strip() if (person_first and person_last) else ""

    # Groups expose their displayed title via `description` (and sometimes
    # `name`) instead of an identity, so include those so group chats match by
    # the header title shown in Signal.
    group_description = getattr(target, "description", "") or ""
    group_name = getattr(target, "name", "") or ""

    for value in [
        full_name,
        person_full,
        identity_first,
        person_first,
        group_description,
        group_name,
        slug,
    ]:
        if value and value not in aliases:
            aliases.append(value)

    if slug:
        for variant in [slug.replace("-", " "), slug.replace("_", " "), slug.replace("-", ""), slug.replace("_", "")]:
            if variant and variant not in aliases:
                aliases.append(variant)

    normalized_unique: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        key = normalize_text(alias)
        if key and key not in seen:
            seen.add(key)
            normalized_unique.append(alias)

    return normalized_unique or ["unknown"]


def build_target_index(targets: list[Any]) -> dict[str, list[Any]]:
    index: dict[str, list[Any]] = {}
    for target in targets:
        for alias in build_target_aliases(target):
            key = normalize_text(alias)
            if not key:
                continue
            index.setdefault(key, []).append(target)
    return index


def resolve_target_for_conversation(label: str, target_index: dict[str, list[Any]]) -> Any | None:
    label_key = normalize_text(label)
    if not label_key:
        return None

    direct = target_index.get(label_key)
    if direct:
        return direct[0]

    # Fallback: choose the closest alias by containment and longest alias token.
    best_target = None
    best_rank = None
    for alias_key, targets in target_index.items():
        if alias_key in label_key or label_key in alias_key:
            rank = (0 if alias_key == label_key else 1, -len(alias_key))
            if best_rank is None or rank < best_rank:
                best_rank = rank
                best_target = targets[0]

    return best_target


def slugify_filename(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text.strip())
    return re.sub(r"_+", "_", text).strip("_") or "attachment"


def guess_extension(content_type: str | None, fallback_name: str = "") -> str:
    if fallback_name:
        suffix = Path(fallback_name).suffix
        if suffix:
            return suffix

    if content_type:
        extension = mimetypes.guess_extension(content_type.split(';', 1)[0].strip().lower())
        if extension:
            return extension

    content_type = (content_type or "").lower()
    special_cases = {
        "image/heic": ".heic",
        "image/heif": ".heif",
        "video/quicktime": ".mov",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "image/webp": ".webp",
    }
    return special_cases.get(content_type, ".bin")


def build_saved_name(slug: str, timestamp: str, index: int, content_type: str | None, original_name: str = "") -> str:
    prefix = slugify_filename(slug)
    time_part = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    extension = guess_extension(content_type, original_name)
    return f"{prefix}_{time_part}_{index:03d}{extension}"


def ensure_media_folder(output_root: Path, slug: str, create: bool = False) -> Path:
    media_dir = output_root / "People" / slug / "media"
    if create:
        media_dir.mkdir(parents=True, exist_ok=True)
    return media_dir


def snapshot_files(folder: Path) -> set[Path]:
    if not folder.exists():
        return set()
    return {path for path in folder.iterdir() if path.is_file()}


def file_content_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def wait_for_new_file(folder: Path, before: set[Path], timeout: float, poll_interval: float) -> Path:
    deadline = time.time() + timeout
    while time.time() < deadline:
        current = snapshot_files(folder)
        created = sorted(current - before, key=lambda path: path.stat().st_mtime, reverse=True)
        if created:
            return created[0]
        time.sleep(poll_interval)
    raise TimeoutError(f"No new file appeared in {folder} within {timeout} seconds")


def render_media_link(record: MediaRecord) -> str:
    target = record.markdown_target.replace('\\', '/')
    if record.media_kind == "video":
        return f"[{record.saved_filename}]({target})"
    return f"![]({target})"


def replace_media_links(text: str, records: Iterable[MediaRecord]) -> str:
    records_by_key: dict[str, MediaRecord] = {}
    for record in records:
        records_by_key[record.source_label] = record
        records_by_key[record.saved_filename] = record
        records_by_key[Path(record.saved_filename).stem] = record

    def replace_match(match: re.Match[str]) -> str:
        bang = match.group(1)
        target = match.group(2).strip()
        alias = match.group(3)
        record = records_by_key.get(target) or records_by_key.get(Path(target).stem)
        if not record:
            return match.group(0)
        if bang:
            return render_media_link(record)
        return f"[{alias or record.saved_filename}]({record.markdown_target.replace('\\', '/')})"

    return WIKILINK_RE.sub(replace_match, text)


def update_markdown_files(output_root: Path, slug: str, records: list[MediaRecord]) -> list[Path]:
    slug_root = output_root / "People" / slug
    if not slug_root.exists():
        # Backward compatibility for older exports that may not use People/<slug>.
        slug_root = output_root / slug
    if not slug_root.exists():
        return []

    changed: list[Path] = []
    markdown_files = sorted(slug_root.rglob("*.md"))
    for markdown_file in markdown_files:
        original = markdown_file.read_text(encoding="utf-8")
        updated = replace_media_links(original, records)
        if updated != original:
            markdown_file.write_text(updated, encoding="utf-8")
            changed.append(markdown_file)

    return changed


def flatten_people(the_config: config.Config) -> list[Any]:
    targets: list[Any] = []
    for item in getattr(the_config, "people", []):
        targets.append(item)
    for item in getattr(the_config, "groups", []):
        targets.append(item)
    return targets


class SignalUiDriver:
    def __init__(self, settings: AutomationSettings):
        self.settings = settings
        self.app = None
        self.window = None
        self._seen_message_keys: set[tuple[int, int, int, int]] = set()

    def launch(self) -> None:
        signal_exe = self.settings.signal_exe or self.discover_signal_exe()
        if not signal_exe:
            return
        if Application is None:
            raise RuntimeError("pywinauto is not installed")
        logging.info("Launching Signal Desktop: %s", signal_exe)
        self.app = Application(backend="uia").start(signal_exe)

        # Give Electron time to render before first connect attempt.
        deadline = time.time() + max(1.0, self.settings.startup_wait_seconds)
        last_error = None
        while time.time() < deadline:
            try:
                self.connect()
                return
            except Exception as exc:
                last_error = exc
                time.sleep(0.4)

        if last_error:
            raise RuntimeError(f"Signal launched but could not attach to its window: {last_error}")

    def ensure_running(self) -> None:
        # Connect to an already-open Signal window; if none exists, try to launch
        # Signal from a configured or discovered path.
        try:
            self.connect()
            return
        except Exception:
            self.window = None

        signal_exe = self.settings.signal_exe or self.discover_signal_exe()
        if not signal_exe:
            raise RuntimeError(
                "Signal Desktop is not running and could not be found automatically. "
                "Launch Signal first, or pass --signal-exe with the path to Signal.exe."
            )
        self.settings.signal_exe = signal_exe
        self.launch()

    @staticmethod
    def discover_signal_exe() -> str:
        if not IS_WINDOWS:
            return ""

        candidates = [
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\signal-desktop\Signal.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Signal\Signal.exe"),
            os.path.expandvars(r"%ProgramFiles%\Signal\Signal.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Signal\Signal.exe"),
        ]
        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return candidate
        return ""

    @staticmethod
    def _to_pywinauto_keys(shortcut: list[str]) -> str:
        # Use pywinauto send_keys chord syntax to avoid modifier key timing issues.
        token_map = {
            "ctrl": "^",
            "control": "^",
            "shift": "+",
            "alt": "%",
            "pagedown": "{PGDN}",
            "pgdn": "{PGDN}",
            "pageup": "{PGUP}",
            "pgup": "{PGUP}",
            "enter": "{ENTER}",
            "esc": "{ESC}",
            "escape": "{ESC}",
        }

        modifiers = ""
        keys: list[str] = []
        for part in shortcut:
            key = part.strip().lower()
            mapped = token_map.get(key)
            if mapped in ("^", "+", "%"):
                modifiers += mapped
            elif mapped:
                keys.append(mapped)
            elif len(key) == 1:
                keys.append(key)
            else:
                keys.append("{" + key.upper() + "}")

        return modifiers + "".join(keys)

    def connect(self) -> None:
        if Application is None:
            raise RuntimeError("pywinauto is not installed")

        # If we launched Signal ourselves, connect by process id first.
        launched_pid = getattr(self.app, "process", None)
        if launched_pid:
            try:
                self.app = self.app.connect(process=launched_pid)
                self.window = self.app.top_window()
                self.window.set_focus()
                return
            except Exception:
                pass

        self.app = self.app or Application(backend="uia")
        if Desktop is None:
            raise RuntimeError("pywinauto Desktop API is not available")

        candidates = Desktop(backend="uia").windows(
            title_re=f".*{re.escape(self.settings.window_title)}.*",
            control_type="Window",
            visible_only=True,
        )

        # Only keep windows that actually belong to Signal (signal.exe).
        # Without this, a browser window/tab whose title merely contains
        # "Signal" (e.g. Chrome) would be matched and driven by mistake.
        signal_windows = [w for w in candidates if self._window_is_signal(w)]
        if signal_windows:
            candidates = signal_windows
        elif candidates:
            titles = ", ".join(sorted({(w.window_text() or "").strip() for w in candidates}))
            raise RuntimeError(
                "Found window(s) matching the title but none owned by signal.exe "
                f"(matched: {titles}). Is Signal Desktop running? "
                "Launch Signal first, or pass --signal-exe to start it."
            )

        if not candidates:
            raise RuntimeError(
                f"Could not find a visible Signal window matching '{self.settings.window_title}'. "
                "Launch Signal Desktop first, or pass --signal-exe to start it."
            )

        title_lower = self.settings.window_title.lower()

        # Prefer exact title match, then titles starting with the requested label.
        ranked = sorted(
            candidates,
            key=lambda w: (
                0 if (w.window_text() or "").strip().lower() == title_lower else 1,
                0 if (w.window_text() or "").strip().lower().startswith(title_lower) else 1,
                len((w.window_text() or "").strip()),
            ),
        )

        self.window = ranked[0]
        self.window.set_focus()

    @staticmethod
    def _window_is_signal(win) -> bool:
        # Resolve the owning process image name for a window and confirm it is
        # Signal Desktop, so we never drive a browser window titled "Signal".
        try:
            pid = win.process_id()
        except Exception:
            try:
                pid = win.element_info.process_id
            except Exception:
                return False

        if not pid:
            return False

        if not IS_WINDOWS:
            return True

        try:
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if not handle:
                return False
            try:
                buf_len = wintypes.DWORD(1024)
                buf = ctypes.create_unicode_buffer(buf_len.value)
                ok = kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(buf_len))
                if not ok:
                    return False
                image = (buf.value or "").lower()
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False

        name = Path(image).name
        return name == "signal.exe" or "signal" in name

    def _bring_to_foreground(self) -> None:
        # pywinauto's set_focus() does not reliably make the window the true OS
        # foreground window, which pyautogui keystrokes require. Force it via the
        # Win32 API using the window handle so shortcuts like Ctrl+Shift+M land
        # in Signal instead of being dropped.
        if self.window is None:
            return

        handle = None
        try:
            handle = self.window.handle
        except Exception:
            handle = None

        if handle:
            try:
                import ctypes

                user32 = ctypes.windll.user32
                SW_RESTORE = 9
                user32.ShowWindow(handle, SW_RESTORE)
                # Attach to the foreground thread so SetForegroundWindow is allowed.
                fg_window = user32.GetForegroundWindow()
                fg_thread = user32.GetWindowThreadProcessId(fg_window, None)
                cur_thread = ctypes.windll.kernel32.GetCurrentThreadId()
                target_thread = user32.GetWindowThreadProcessId(handle, None)
                user32.AttachThreadInput(cur_thread, fg_thread, True)
                user32.AttachThreadInput(cur_thread, target_thread, True)
                user32.BringWindowToTop(handle)
                user32.SetForegroundWindow(handle)
                user32.AttachThreadInput(cur_thread, fg_thread, False)
                user32.AttachThreadInput(cur_thread, target_thread, False)
                time.sleep(0.15)
                return
            except Exception:
                pass

        try:
            self.window.set_focus()
        except Exception:
            pass

    def _send_shortcut(self, shortcut: list[str]) -> None:
        if self.window is not None:
            self._bring_to_foreground()

        keys = [k.strip().lower() for k in shortcut if k.strip()]

        # Preferred path: hardware scan codes via SendInput, which Electron apps
        # (Signal) accept where pyautogui's virtual-key events are ignored.
        if send_scancode_shortcut(keys):
            return

        if pyautogui is not None:
            try:
                for key in keys:
                    pyautogui.keyDown(key)
                    time.sleep(0.03)
                for key in reversed(keys):
                    pyautogui.keyUp(key)
                    time.sleep(0.03)
            except Exception:
                pyautogui.hotkey(*keys)
            return

        if send_keys is None:
            raise RuntimeError("No keyboard backend is available")

        send_keys(self._to_pywinauto_keys(shortcut), pause=0.03, with_spaces=True)

    def _clear_clipboard(self) -> None:
        if not IS_WINDOWS:
            return
        user32 = ctypes.windll.user32
        if user32.OpenClipboard(0):
            try:
                user32.EmptyClipboard()
            finally:
                user32.CloseClipboard()

    def _read_clipboard_text(self) -> str:
        if not IS_WINDOWS:
            return ""
        CF_UNICODETEXT = 13
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.GetClipboardData.argtypes = [wintypes.UINT]
        user32.GetClipboardData.restype = wintypes.HANDLE
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = wintypes.LPVOID
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]

        if not user32.OpenClipboard(0):
            return ""
        try:
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return ""
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                return ""
            try:
                return ctypes.c_wchar_p(ptr).value or ""
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()

    def _read_conversation_name_via_clipboard(self) -> str:
        """Select-all + copy the open conversation and parse the header name."""
        if self.window is not None:
            self._bring_to_foreground()

        # Ctrl+J selects the last message, putting focus in the message pane, so
        # the following Ctrl+A selects the conversation transcript (not the
        # search box). Then Ctrl+C copies it for name extraction.
        if not send_scancode_shortcut(["ctrl", "j"]):
            self._send_shortcut(["ctrl", "j"])
        time.sleep(0.2)

        self._clear_clipboard()
        self._send_shortcut(["ctrl", "a"])
        time.sleep(0.15)
        self._send_shortcut(["ctrl", "c"])
        time.sleep(0.25)

        text = self._read_clipboard_text()
        if not text:
            return ""
        return parse_conversation_name_from_clipboard(text)

    def _mouse_move_click_screen(self, x: int, y: int, button: str = "left") -> None:
        if pyautogui is not None:
            duration = max(0.02, float(self.settings.mouse_move_duration_seconds))
            # Small pre-move to make cursor movement obvious while debugging.
            pyautogui.moveTo(max(0, x - 2), max(0, y - 2), duration=duration)
            pyautogui.moveTo(x, y, duration=duration)
            if button == "right":
                pyautogui.mouseDown(button="right")
                time.sleep(0.04)
                pyautogui.mouseUp(button="right")
            else:
                pyautogui.click(button=button)
            return

        if self.settings.require_visible_mouse:
            raise RuntimeError(
                "Visible mouse backend is required but pyautogui is unavailable in this interpreter. "
                "Install pyautogui or run with --no-require-visible-mouse."
            )

        if self.window is None:
            self.connect()
        assert self.window is not None
        rect = self.window.rectangle()
        rel_x = max(1, x - rect.left)
        rel_y = max(1, y - rect.top)
        self.window.click_input(button=button, coords=(rel_x, rel_y))

    def focus_conversation_area(self) -> None:
        if self.window is None:
            self.connect()
        assert self.window is not None

        self.window.set_focus()
        try:
            rect = self.window.rectangle()
            # Click in the right pane where conversation messages are shown.
            x = int(rect.left + (rect.width() * 0.72))
            y = int(rect.top + (rect.height() * 0.38))
            self._mouse_move_click_screen(x, y, button="left")
        except Exception as exc:
            if self.settings.require_visible_mouse:
                raise RuntimeError(f"Failed to move/click mouse in conversation area: {exc}") from exc
            # Fallback to generic focus only.
            self.window.set_focus()

    def _click_to_deselect(self) -> None:
        # Clear the active Ctrl+A text selection with a single left click in the
        # EMPTY middle area of the message pane - NOT on a message bubble.
        # Clicking a bubble moves keyboard focus into that message and suppresses
        # Ctrl+Shift+M. The process is DPI-aware (set at import), so computed
        # screen coordinates line up with pyautogui's click coordinates.
        if self.window is None:
            self.connect()
        assert self.window is not None

        self.window.set_focus()
        rect = self.window.rectangle()
        x = int(rect.left + (rect.width() * 0.68))
        y = int(rect.top + (rect.height() * 0.50))
        logging.info(
            "Deselect click at screen (%d, %d) window L%d T%d R%d B%d (w=%d h=%d)",
            x, y, rect.left, rect.top, rect.right, rect.bottom, rect.width(), rect.height(),
        )
        self._mouse_move_click_screen(x, y, button="left")

    def go_to_top_of_conversation(self) -> None:
        self.focus_conversation_area()
        self._send_shortcut(["home"])
        time.sleep(0.2)

    def reset_message_scan(self) -> None:
        self._seen_message_keys.clear()

    def open_conversation_by_shortcut(self, index: int) -> None:
        if index < 1:
            raise RuntimeError("Conversation shortcut index must be >= 1")
        if self.window is not None:
            try:
                self.window.set_focus()
            except Exception:
                pass
        if index <= 9:
            logging.info("Sending Ctrl+%d", index)
            self._send_shortcut(["ctrl", str(index)])
        elif index == 10:
            logging.info("Sending Ctrl+0")
            self._send_shortcut(["ctrl", "0"])
        else:
            raise RuntimeError("Only Ctrl+1..Ctrl+0 shortcuts are supported")
        time.sleep(0.35)

    def _find_named_descendant(self, control_type: str, names: list[str]):
        assert self.window is not None
        try:
            nodes = self.window.descendants(control_type=control_type)
        except Exception:
            nodes = []

        wanted = [normalize_text(name) for name in names if name]
        for node in nodes:
            text = getattr(node, "window_text", lambda: "")()
            if not text:
                try:
                    text = node.element_info.name or ""
                except Exception:
                    text = ""
            key = normalize_text(text)
            if key in wanted:
                return node
        return None

    def _trigger_download_from_menu(self) -> None:
        if self.window is None:
            self.connect()
        assert self.window is not None

        # Try explicit menu button labels first.
        menu_button = self._find_named_descendant("Button", ["More", "More options", "Menu", "..."])
        if menu_button is not None:
            menu_button.click_input()
            time.sleep(0.2)
        else:
            # Fallback to context menu key if no overflow button is exposed.
            self._send_shortcut(["shift", "f10"])
            time.sleep(0.2)

        download_item = self._find_named_descendant("MenuItem", ["Download", "Save", "Save as"])
        if download_item is None:
            raise RuntimeError("Could not find Download item after opening the message menu")

        download_item.click_input()

    def _log_foreground_window(self, when: str) -> None:
        if not IS_WINDOWS:
            return
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            pid = wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            logging.info("Foreground window %s: hwnd=%s title=%r pid=%s", when, hwnd, buf.value, pid.value)
        except Exception:
            logging.exception("Failed to read foreground window %s", when)

    def _media_panel_present(self) -> bool:
        # Heuristic: after Ctrl+Shift+M Signal shows an "All Media" / media
        # gallery panel. Look for UIA text nodes whose name mentions media.
        if self.window is None:
            return False
        try:
            for control_type in ("Text", "Button", "TabItem", "Group"):
                for node in self.window.descendants(control_type=control_type):
                    name = ""
                    try:
                        name = node.window_text() or node.element_info.name or ""
                    except Exception:
                        name = ""
                    n = normalize_text(name)
                    if n in {"all media", "media", "photos", "files"} or "all media" in n:
                        return True
        except Exception:
            pass
        return False

    def close_open_panels(self) -> None:
        # Close any AllMedia panel / media preview / details drawer left open by
        # the PREVIOUS conversation. In Signal, Escape = popPanelForConversation
        # (it pops one open panel and does NOT close the conversation). Without
        # this, the next conversation still shows the previous media gallery, so
        # name extraction copies the gallery instead of the transcript AND
        # Ctrl+Shift+M does not reveal a fresh media tab. Two Escapes cover a
        # stacked panel + preview. This mirrors the reset the diagnostic does
        # right after opening a conversation, which is what made it work.
        for _ in range(2):
            if not send_scancode_shortcut(["escape"]):
                self._send_shortcut(["escape"])
            time.sleep(0.25)

    def open_media_view(self) -> None:
        # Close any leftover Windows Save dialog FIRST. An orphaned dialog (from a
        # previous run) steals keyboard focus, so Ctrl+Shift+M would go to the
        # dialog and the media panel would never open ("Media panel NOT detected").
        strays = self._win32_close_save_dialogs()
        if strays:
            logging.info("Closed %d leftover Save dialog(s) before opening media", strays)
            self._bring_to_foreground()
            time.sleep(0.3)
        # NOTE: deliberately do NOT call _bring_to_foreground() here. Signal is
        # already the foreground window from the immediately-preceding name
        # extraction (get_current_conversation_title -> _send_shortcut brings it
        # forward). Re-activating the window right before Ctrl+Shift+M suppresses
        # the media tab (documented gotcha) and is the one thing the working
        # diagnostic did NOT do before the shortcut.
        # Clear the Ctrl+A text selection left over from name extraction BEFORE
        # sending Ctrl+Shift+M. A mouse click is unreliable here: at any realistic
        # coordinate in a full conversation it lands ON a message bubble, which
        # puts Signal into "message-focused" mode and SUPPRESSES Ctrl+Shift+M, so
        # the media tab never opens. Instead press Ctrl+J, which drops the text
        # selection and focuses the last message at the conversation level - the
        # confirmed-working state from which Ctrl+Shift+M opens All Media. Do NOT
        # call _bring_to_foreground() between here and the shortcut; a re-activate
        # in that gap also suppresses the media tab.
        logging.info("Sending Ctrl+J to clear selection and focus last message")
        if not send_scancode_shortcut(["ctrl", "j"]):
            self._send_shortcut(["ctrl", "j"])
        # Short settle so the selection clears before the shortcut, but keep it
        # brief: Ctrl+Shift+M must follow as the very next action.
        time.sleep(0.3)
        self._log_foreground_window("before Ctrl+Shift+M")
        logging.info("Sending Ctrl+Shift+M to open media view")
        # Delivery matters here: hardware-scancode SendInput does NOT open All
        # Media in this Signal build (confirmed via diagnose_media_tab.py), but
        # pyautogui.hotkey does. Use it as the primary path, falling back to
        # scancode only if pyautogui is unavailable.
        if pyautogui is not None:
            pyautogui.hotkey("ctrl", "shift", "m")
        elif not send_scancode_shortcut(["ctrl", "shift", "m"]):
            self._send_shortcut(["ctrl", "shift", "m"])
        time.sleep(1.5)
        self._log_foreground_window("after Ctrl+Shift+M")
        if self._media_panel_present():
            logging.info("Media panel detected in UIA tree")
        else:
            logging.warning("Media panel NOT detected after Ctrl+Shift+M")
        # The media tab slides into place; give it a couple of seconds to finish
        # animating before anything else is sent, otherwise it never settles.
        time.sleep(2.0)

    def advance_media_item(self) -> None:
        self._send_shortcut(["right"])
        time.sleep(0.08)
        self._send_shortcut(["tab"])
        time.sleep(0.2)

    def enter_media_tab_and_open_first(self) -> None:
        # After Ctrl+Shift+M the media panel has slid into place. Press Tab once
        # to move focus into the media grid, landing on the first (most recent)
        # item, then Enter to open that item in the media preview.
        self._send_shortcut(["tab"])
        time.sleep(0.4)
        self._send_shortcut(["enter"])
        time.sleep(0.6)

    def previous_media_item(self) -> None:
        # In the media preview, Left arrow steps to the previous (older) item.
        self._send_shortcut(["left"])
        time.sleep(0.35)

    def exit_media_preview(self) -> None:
        # Escape closes the media preview and returns to the media list.
        self._send_shortcut(["escape"])
        time.sleep(0.3)

    def save_media_preview_item(self, destination_dir: Path, desired_name: str) -> Path:
        # In the media preview, Ctrl+S saves the current item via the Windows
        # Save dialog. Returns the renamed saved file path.
        destination_dir.mkdir(parents=True, exist_ok=True)
        before = snapshot_files(destination_dir)

        # Start from a clean slate: close any Save dialogs left open by a prior
        # failed attempt so we never drive a stale/background dialog and never
        # stack them. Then re-focus Signal so Ctrl+S opens a fresh dialog.
        closed = self._close_all_save_dialogs()
        if closed:
            logging.info("Closed %d stray Save dialog(s) before saving", closed)
            self._bring_to_foreground()
            time.sleep(0.2)

        self._send_shortcut(["ctrl", "s"])
        time.sleep(0.4)
        try:
            self._handle_windows_save_dialog(destination_dir)
        except RuntimeError as exc:
            raise TimeoutError(str(exc)) from exc

        created = wait_for_new_file(
            destination_dir,
            before,
            self.settings.attachment_wait_seconds,
            self.settings.poll_interval_seconds,
        )
        target = destination_dir / desired_name
        # Preserve the REAL extension from the file Signal actually wrote (e.g.
        # .jpg/.jpeg/.mp4/.mov). desired_name is often ".bin" because the content
        # type is unknown up front; renaming to that would corrupt the extension.
        if created.suffix and created.suffix.lower() != target.suffix.lower():
            target = target.with_suffix(created.suffix)
        if target.exists():
            target.unlink()
        created.rename(target)
        return target

    def _open_media_item_menu(self) -> bool:
        if self.window is None:
            self.connect()
        assert self.window is not None

        self.window.set_focus()
        try:
            sequences = [
                [],
                ["tab"],
                ["right", "tab"],
            ]
            for sequence in sequences:
                for key in sequence:
                    self._send_shortcut([key])
                    time.sleep(0.08)
                if send_keys is not None:
                    send_keys("+{F10}", pause=0.02, with_spaces=True)
                elif pyautogui is not None:
                    pyautogui.hotkey("shift", "f10")
                else:
                    return False
                time.sleep(0.18)
                if self._get_first_context_menu_item() is not None:
                    return True
                self._dismiss_context_menu()
            self._dismiss_context_menu()
            return False
        except Exception:
            self._dismiss_context_menu()
            return False

    def _select_save_from_media_menu(self) -> bool:
        try:
            # Let the context menu fully render before navigating.
            time.sleep(max(0.4, self.settings.menu_key_delay_seconds))
            # Do NOT refocus the window here: focusing the main window would
            # dismiss the open context menu (looks like an Escape press).
            self._send_menu_key("down")
            self._send_menu_key("down")
            self._send_menu_key("down")
            self._send_menu_key("enter")
            return True
        except Exception:
            return False

    def _send_menu_key(self, key: str) -> None:
        # Send a single navigation key to the currently open context menu
        # WITHOUT calling window.set_focus(), which would close the menu.
        delay = max(0.3, self.settings.menu_key_delay_seconds)
        if send_scancode_shortcut([key]):
            time.sleep(delay)
            return
        if pyautogui is not None:
            pyautogui.press(key)
            time.sleep(delay)
            return
        if send_keys is not None:
            send_keys(self._to_pywinauto_keys([key]), pause=0.02, with_spaces=True)
            time.sleep(delay)
            return
        raise RuntimeError("No keyboard backend is available for menu navigation")

    def _collect_message_candidates(self):
        if self.window is None:
            self.connect()
        assert self.window is not None

        rect = self.window.rectangle()
        mid_x = (rect.left + rect.right) // 2
        candidates = []

        for control_type in ["ListItem", "DataItem", "Pane"]:
            try:
                nodes = self.window.descendants(control_type=control_type)
            except Exception:
                nodes = []

            for node in nodes:
                try:
                    r = node.rectangle()
                except Exception:
                    continue

                if r.width() <= 16 or r.height() <= 16:
                    continue
                if r.right <= mid_x:
                    continue

                key = (int(r.left), int(r.top), int(r.right), int(r.bottom))
                candidates.append((key, node, r))

        candidates.sort(key=lambda item: (item[2].top, item[2].left))
        return candidates

    def _get_first_context_menu_item(self):
        if Desktop is None:
            return None
        try:
            menus = Desktop(backend="uia").windows(control_type="Menu", visible_only=True)
        except Exception:
            menus = []

        for menu in menus:
            try:
                items = menu.descendants(control_type="MenuItem")
            except Exception:
                items = []
            if not items:
                continue
            try:
                items = sorted(items, key=lambda item: (item.rectangle().top, item.rectangle().left))
            except Exception:
                pass
            return items[0]
        return None

    def _click_menu_item_with_right_offset(self, menu_item) -> bool:
        try:
            rect = menu_item.rectangle()
            # Hover over the item, move ~10px right so it becomes active, then click.
            base_x = int(rect.left + max(2, min(8, rect.width() // 10)))
            x = int(base_x + max(1, self.settings.context_menu_right_nudge_px))
            y = int(rect.top + max(6, rect.height() // 2))

            if pyautogui is not None:
                duration = max(0.02, float(self.settings.mouse_move_duration_seconds))
                pyautogui.moveTo(base_x, y, duration=duration)
                time.sleep(0.06)
                pyautogui.moveTo(x, y, duration=duration)
                time.sleep(0.06)
                pyautogui.click()
                return True

            rel_x = max(2, min(rect.width() - 2, 10 + max(1, self.settings.context_menu_right_nudge_px)))
            rel_y = max(2, min(rect.height() - 2, rect.height() // 2))
            menu_item.move_mouse_input(coords=(rel_x, rel_y))
            time.sleep(0.06)
            menu_item.click_input(coords=(rel_x, rel_y))
            return True
        except Exception:
            try:
                menu_item.click_input()
                return True
            except Exception:
                return False

    def _activate_download_menu_item(self, menu_item) -> bool:
        # Mouse-only path is intentionally preferred here because Signal's
        # context menu highlight state can differ from logical focus.
        return self._click_menu_item_with_right_offset(menu_item)

    def _dismiss_context_menu(self) -> None:
        try:
            if send_keys is not None:
                send_keys("{ESC}", pause=0.01, with_spaces=True)
            elif pyautogui is not None:
                pyautogui.press("esc")
        except Exception:
            pass

    def _right_click_screen_point(self, x: int, y: int) -> bool:
        try:
            self._mouse_move_click_screen(x, y, button="right")
            return True
        except Exception:
            return False

    def _trigger_download_from_probe_points(self) -> bool:
        if self.window is None:
            self.connect()
        assert self.window is not None

        self.focus_conversation_area()

        rect = self.window.rectangle()
        # Probe several points on the right conversation pane from top to bottom.
        x = int(rect.left + (rect.width() * 0.86))
        y_positions = [
            int(rect.top + (rect.height() * 0.26)),
            int(rect.top + (rect.height() * 0.36)),
            int(rect.top + (rect.height() * 0.46)),
            int(rect.top + (rect.height() * 0.56)),
            int(rect.top + (rect.height() * 0.66)),
        ]

        for y in y_positions:
            if not self._right_click_screen_point(x, y):
                continue

            time.sleep(0.15)
            first_item = self._get_first_context_menu_item()
            if first_item is None:
                self._dismiss_context_menu()
                continue

            label = ""
            try:
                label = first_item.window_text() or first_item.element_info.name or ""
            except Exception:
                label = ""

            if not normalize_text(label).startswith("download"):
                self._dismiss_context_menu()
                continue

            if self._activate_download_menu_item(first_item):
                return True

            self._dismiss_context_menu()

        return False

    def _trigger_download_from_message_context(self) -> bool:
        # Media viewer workflow: right click the current image, then use
        # Down x3 + Enter to reach Save.
        if not self._open_media_item_menu():
            return False

        if not self._select_save_from_media_menu():
            self._dismiss_context_menu()
            return False

        return True

    def _win32_find_save_dialogs(self) -> list[int]:
        # HWNDs of every visible top-level "Save" dialog (window class "#32770").
        # Win32 sees dialogs that the UIA Desktop enumeration sometimes misses.
        if not IS_WINDOWS:
            return []
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        handles: list[int] = []

        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def _cb(hwnd, _lparam):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                cls = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cls, 256)
                if cls.value != "#32770":
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = (buf.value or "").strip().lower()
                if title.startswith("save"):
                    handles.append(int(hwnd))
            except Exception:
                pass
            return True

        try:
            user32.EnumWindows(EnumWindowsProc(_cb), 0)
        except Exception:
            return []
        return handles

    def _win32_close_save_dialogs(self) -> int:
        # Close every top-level Windows "Save" dialog via the Win32 API. This
        # catches ORPHANED dialogs left by dead python processes that the UIA
        # Desktop enumeration cannot see (and which otherwise steal keyboard focus
        # so Ctrl+Shift+M / Ctrl+S never reach Signal).
        if not IS_WINDOWS:
            return 0
        import ctypes

        user32 = ctypes.windll.user32
        WM_CLOSE = 0x0010
        handles = self._win32_find_save_dialogs()
        for hwnd in handles:
            try:
                user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            except Exception:
                pass
        if handles:
            time.sleep(0.3)
        return len(handles)

    def _list_save_dialogs(self) -> list:
        # Every currently-open Windows "Save As" / "Save" / overwrite-confirm
        # dialog, in the order the OS returns them.
        if Desktop is None:
            return []
        found: list = []
        try:
            for w in Desktop(backend="uia").windows(control_type="Window", visible_only=True):
                try:
                    title = normalize_text(w.window_text() or "")
                except Exception:
                    continue
                if title in {"save as", "save", "save your file", "confirm save as"} or title.startswith("save"):
                    found.append(w)
        except Exception:
            return found
        return found

    def _close_all_save_dialogs(self) -> int:
        # Cancel EVERY open Save dialog. Retries used to stack multiple dialogs,
        # after which the handler drove a background one (leaving the visible top
        # dialog untouched and never saving). Starting each save from zero open
        # dialogs removes that ambiguity. Win32 close runs first because it also
        # reaches orphaned dialogs that UIA cannot see.
        closed = self._win32_close_save_dialogs()
        for _ in range(8):
            dialogs = self._list_save_dialogs()
            if not dialogs:
                break
            dlg = dialogs[0]
            try:
                dlg.set_focus()
            except Exception:
                pass
            done = False
            try:
                btn = dlg.child_window(title="Cancel", control_type="Button")
                if btn.exists():
                    btn.click_input()
                    done = True
            except Exception:
                done = False
            if not done:
                if send_keys is not None:
                    try:
                        send_keys("{ESC}", pause=0.02)
                    except Exception:
                        pass
                elif pyautogui is not None:
                    pyautogui.press("esc")
            closed += 1
            time.sleep(0.25)
        return closed

    def _handle_windows_save_dialog(self, destination_dir: Path) -> None:
        deadline = time.time() + max(1.0, self.settings.download_action_timeout_seconds)
        hwnd = None
        while time.time() < deadline:
            # Prefer Win32 detection (sees dialogs UIA misses); fall back to UIA.
            found = self._win32_find_save_dialogs()
            if found:
                hwnd = found[-1]
                break
            if self._list_save_dialogs():
                break
            time.sleep(0.2)

        if hwnd is None and not self._list_save_dialogs():
            raise RuntimeError("Download action did not open a Windows Save dialog")

        # Bring THIS dialog to the foreground so keystrokes land in it, not in a
        # stale background dialog.
        if hwnd is not None and IS_WINDOWS:
            try:
                import ctypes

                ctypes.windll.user32.SetForegroundWindow(hwnd)
                ctypes.windll.user32.BringWindowToTop(hwnd)
            except Exception:
                pass
        else:
            try:
                self._list_save_dialogs()[-1].set_focus()
            except Exception:
                pass
        time.sleep(0.25)

        # PREPEND the destination folder to Signal's pre-filled file name. Alt+N
        # focuses the File name box; Home moves to the start (clearing any
        # selection); typing "<folder>\" turns "IMG_0081.jpg" into
        # "<folder>\IMG_0081.jpg". This preserves the ORIGINAL name + extension
        # (important for videos vs images) without having to read the field, then
        # Enter saves it. wait_for_new_file + rename handle the final name.
        folder_prefix = str(destination_dir)
        if not folder_prefix.endswith("\\"):
            folder_prefix += "\\"

        if send_keys is not None:
            escaped = "".join("{" + c + "}" if c in "{}()+^%~[]" else c for c in folder_prefix)
            send_keys("%n", pause=0.05, with_spaces=True)
            send_keys("{HOME}", pause=0.03, with_spaces=True)
            send_keys(escaped, pause=0.004, with_spaces=True)
            time.sleep(0.1)
            send_keys("{ENTER}", pause=0.03, with_spaces=True)
        elif pyautogui is not None:
            pyautogui.hotkey("alt", "n")
            time.sleep(0.05)
            pyautogui.press("home")
            pyautogui.typewrite(folder_prefix, interval=0.005)
            time.sleep(0.1)
            pyautogui.press("enter")
        else:
            raise RuntimeError("No keyboard backend available to interact with Save dialog")

        # If a dialog is still open (e.g. an overwrite "Confirm Save As", or Enter
        # didn't land on Save), press Enter once more. Do NOT cancel here - the
        # next save starts by closing any strays via _close_all_save_dialogs.
        time.sleep(0.4)
        if self._win32_find_save_dialogs():
            if send_keys is not None:
                try:
                    send_keys("{ENTER}", pause=0.03, with_spaces=True)
                except Exception:
                    pass
            elif pyautogui is not None:
                pyautogui.press("enter")

    def _find_conversation_list_item(self, aliases: list[str]):
        assert self.window is not None

        try:
            list_items = self.window.descendants(control_type="ListItem")
        except Exception:
            list_items = []

        best_item = None
        best_score = None

        normalized_aliases = [normalize_text(alias) for alias in aliases if normalize_text(alias)]

        for item in list_items:
            name = getattr(item, "window_text", lambda: "")()
            if not name:
                try:
                    name = item.element_info.name or ""
                except Exception:
                    name = ""

            name_n = normalize_text(name)
            if not name_n:
                continue

            for alias_n in normalized_aliases:
                score = None
                if name_n == alias_n:
                    score = 0
                elif alias_n in name_n:
                    score = 1
                elif name_n in alias_n:
                    score = 2

                if score is None:
                    continue

                tie_break = len(name_n)
                rank = (score, tie_break)
                if best_score is None or rank < best_score:
                    best_score = rank
                    best_item = item

        return best_item

    def _open_conversation_via_search(self, aliases: list[str]) -> bool:
        if not self.settings.allow_search_fallback:
            return False

        for alias in aliases:
            try:
                self._send_shortcut(self.settings.conversation_search_shortcut)
                time.sleep(0.2)

                if send_keys is not None:
                    send_keys("^a{BACKSPACE}", pause=0.02, with_spaces=True)
                    send_keys(alias, pause=0.02, with_spaces=True)
                    send_keys("{ENTER}", pause=0.02, with_spaces=True)
                elif pyautogui is not None:
                    pyautogui.hotkey("ctrl", "a")
                    pyautogui.press("backspace")
                    pyautogui.write(alias, interval=0.01)
                    pyautogui.press("enter")
                else:
                    continue

                time.sleep(0.3)
                return True
            except Exception:
                continue

        return False

    def activate_target(self, label: str, aliases: list[str] | None = None) -> None:
        if self.window is None:
            self.connect()

        assert self.window is not None
        self.window.set_focus()

        alias_list = aliases or [label]

        item = self._find_conversation_list_item(alias_list)
        if item is not None:
            item.click_input()
            return

        if self._open_conversation_via_search(alias_list):
            return

        if self.settings.use_ocr:
            self._activate_target_with_ocr(label)
            return

        raise RuntimeError(f"Could not locate conversation '{label}' in Signal using list lookup or search")

    def get_current_conversation_title(self, retries: int = 5) -> str:
        # Read the header title of the currently open conversation. In Signal
        # Desktop the contact/group name is the first/topmost text at the top of
        # the right-hand conversation pane. It can render as a Text node or as a
        # Button (the header opens conversation details), and it may take a moment
        # to appear after switching conversations, so retry a few times.
        if self.window is None:
            self.connect()
        assert self.window is not None

        for attempt in range(max(1, retries)):
            # Primary: select-all + copy, then parse the header name from the
            # clipboard. This is far more reliable than reading UIA nodes.
            title = self._read_conversation_name_via_clipboard()
            # Validate: the clipboard parse can latch onto a message body (e.g.
            # "I am leaving that to you...") when a conversation's header is not
            # isolate-wrapped as expected. Reject anything that is not a
            # plausible conversation title so we never match/skip on a sentence.
            if title and is_probable_conversation_title(title):
                return title
            if title:
                logging.info(
                    "Discarding implausible clipboard title (not a name): %r", title
                )
            # Fallback: read the header text nodes from the top of the pane.
            title = self._read_conversation_header_once()
            if title:
                return title
            time.sleep(0.3)
        return ""

    def _read_conversation_header_once(self) -> str:
        assert self.window is not None

        try:
            rect = self.window.rectangle()
        except Exception:
            return ""

        mid_x = (rect.left + rect.right) // 2
        # Header band across the top of the right-hand pane. Keep it generous so
        # we do not miss the title when the window is short or tall.
        header_bottom = rect.top + max(60, int(rect.height() * 0.14))

        candidates: list[tuple[int, int, str]] = []
        raw_texts: list[str] = []
        for control_type in ("Text", "Button", "Hyperlink"):
            try:
                nodes = self.window.descendants(control_type=control_type)
            except Exception:
                nodes = []

            for node in nodes:
                try:
                    r = node.rectangle()
                except Exception:
                    continue
                # Must be in the top band and in the right-hand conversation pane.
                if r.top > header_bottom or r.right <= mid_x:
                    continue

                txt = getattr(node, "window_text", lambda: "")()
                if not txt:
                    try:
                        txt = node.element_info.name or ""
                    except Exception:
                        txt = ""
                txt = txt.strip()
                if not txt:
                    continue
                raw_texts.append(txt)
                if not is_probable_conversation_title(txt):
                    continue
                candidates.append((r.top, r.left, txt))

        if not candidates:
            if raw_texts:
                logging.info("Header region text (none accepted as a title): %s", raw_texts[:12])
            return ""

        # The person's name is the first/topmost text; break ties by left edge.
        candidates.sort(key=lambda c: (c[0], c[1]))
        return candidates[0][2]


    def get_visible_conversation_labels(self, max_count: int = 200) -> list[str]:
        if self.window is None:
            self.connect()

        assert self.window is not None
        self.window.set_focus()

        try:
            list_items = self.window.descendants(control_type="ListItem")
        except Exception:
            list_items = []

        # Some Signal builds expose conversations as DataItem rather than ListItem.
        if not list_items:
            try:
                list_items = self.window.descendants(control_type="DataItem")
            except Exception:
                list_items = []

        labels: list[str] = []
        seen: set[str] = set()

        for item in list_items:
            candidates: list[str] = []

            name = getattr(item, "window_text", lambda: "")()
            if not name:
                try:
                    name = item.element_info.name or ""
                except Exception:
                    name = ""

            if name:
                candidates.append(name.strip())

            # Prefer short text children, which are often the conversation title.
            try:
                text_nodes = item.descendants(control_type="Text")
            except Exception:
                text_nodes = []

            for node in text_nodes:
                txt = getattr(node, "window_text", lambda: "")()
                if txt:
                    candidates.append(txt.strip())

            # Choose the best probable title from this item.
            best = None
            for candidate in candidates:
                if is_probable_conversation_title(candidate):
                    if best is None or len(candidate) < len(best):
                        best = candidate

            if not best:
                continue

            cleaned = normalize_text(best)
            if cleaned not in seen:
                seen.add(cleaned)
                labels.append(best)

            if len(labels) >= max_count:
                break

        # Optional fallback: scrape text labels only when explicitly enabled.
        if not labels and self.settings.allow_text_fallback_scan:
            try:
                text_nodes = self.window.descendants(control_type="Text")
            except Exception:
                text_nodes = []

            for node in text_nodes:
                text = getattr(node, "window_text", lambda: "")()
                cleaned = normalize_text(text)
                if not cleaned or not is_probable_conversation_title(text):
                    continue

                if cleaned not in seen:
                    seen.add(cleaned)
                    labels.append((text or "").strip())

                if len(labels) >= max_count:
                    break

        return labels

    def _activate_target_with_ocr(self, label: str) -> None:
        if not (self.settings.use_ocr and pytesseract and ImageGrab):
            raise RuntimeError("OCR fallback is unavailable")

        image = ImageGrab.grab()
        text = pytesseract.image_to_string(image)
        if label.lower() not in text.lower():
            raise RuntimeError(f"OCR could not find '{label}'")
        raise NotImplementedError("OCR found the conversation, but clicking it still needs a calibrated screen coordinate map")

    def save_current_attachment(self, destination_dir: Path, desired_name: str) -> Path:
        destination_dir.mkdir(parents=True, exist_ok=True)
        before = snapshot_files(destination_dir)

        if not self._trigger_download_from_message_context():
            raise TimeoutError("Could not open Save from media view")

        time.sleep(0.4)
        try:
            self._handle_windows_save_dialog(destination_dir)
        except RuntimeError as exc:
            raise TimeoutError(str(exc)) from exc

        created = wait_for_new_file(destination_dir, before, self.settings.attachment_wait_seconds, self.settings.poll_interval_seconds)
        target = destination_dir / desired_name
        if target.exists():
            target.unlink()
        created.rename(target)
        return target

    def go_to_next_media(self) -> None:
        self._send_shortcut(self.settings.next_item_shortcut)


def validate_signal_executable(signal_exe: str) -> None:
    if not signal_exe:
        return

    lowered = signal_exe.strip().lower()
    basename = Path(lowered).name

    if basename.startswith("python") or basename == "py.exe" or lowered.endswith(".py"):
        raise RuntimeError(
            "Refusing to launch non-Signal executable via --signal-exe. "
            "Use the Signal Desktop executable path, or omit --signal-exe to connect to an already-open Signal window."
        )

    if "windowsapps" in lowered and "python" in lowered:
        raise RuntimeError(
            "--signal-exe points to the Windows Python app alias. "
            "Disable python/python3 app execution aliases or set --signal-exe to Signal.exe."
        )


def validate_ui_runtime(settings: AutomationSettings) -> None:
    # pywinauto can only automate native Windows UI from a Windows Python runtime.
    if not IS_WINDOWS:
        raise RuntimeError(
            "Signal UI automation must run from native Windows Python (PowerShell/cmd), not WSL/Linux. "
            "Use this only from Windows, or run with --dry-run / --manifest-only in WSL."
        )

    if Application is None:
        raise RuntimeError(
            "pywinauto is not available in this interpreter. Install it in your Windows Python environment."
        )


def build_records_for_target(downloads_root: Path, target: Any, media_count: int = 1) -> list[MediaRecord]:
    slug = getattr(target, "slug", "unknown") or "unknown"
    label = getattr(getattr(target, "identity", None), "full_name", slug) or slug
    media_dir = ensure_media_folder(downloads_root, slug, create=False)
    records: list[MediaRecord] = []
    for index in range(media_count):
        saved_filename = build_saved_name(slug, datetime.now().strftime("%Y%m%d_%H%M%S"), index + 1, None)
        saved_path = media_dir / saved_filename
        records.append(
            MediaRecord(
                slug=slug,
                label=label,
                media_kind="image",
                source_label=saved_filename,
                saved_filename=saved_filename,
                saved_path=str(saved_path),
                markdown_target=f"media/{saved_filename}",
            )
        )
    return records


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Windows UI automation for Signal Desktop media capture")

    parser.add_argument("--automation-config", default="config.json", help="JSON config file for message_md and UI automation settings")

    parser.add_argument("-c", "--config-dir", default="", help="message_md config directory")
    parser.add_argument("-s", "--source-folder", default="", help="Signal export source folder")
    parser.add_argument("-f", "--messages-file", default="messages.csv", help="messages CSV file name")
    parser.add_argument("-d", "--debug", action="store_true", help="Preserve source files during setup")
    parser.add_argument("-o", "--output-folder", default="", help="Markdown output folder")
    parser.add_argument("-m", "--me", default="", help="Your slug")
    parser.add_argument("-b", "--begin", default="1900-01-01", help="Begin date")

    parser.add_argument("--signal-exe", default="", help="Path to Signal Desktop executable")
    parser.add_argument("--window-title", default="Signal", help="Signal window title or title fragment")
    parser.add_argument("--conversation-search-shortcut", default="ctrl+k", help="Shortcut to open conversation search")
    parser.add_argument("--allow-search-fallback", action="store_true", help="Allow keyboard text-entry fallback search (can be risky)")
    parser.add_argument("--downloads-root", default="", help="Root folder for downloaded media files")
    parser.add_argument("--state-file", default="", help="State file used for resume")
    parser.add_argument("--log-file", default="", help="Log file for failures")
    parser.add_argument("--save-shortcut", default="ctrl+shift+s", help="Shortcut used to save the current attachment")
    parser.add_argument("--next-item-shortcut", default="pagedown", help="Shortcut used to move to the next media item")
    parser.add_argument("--stop-on-error", action="store_true", help="Stop after the first failure")
    parser.add_argument("--dry-run", action="store_true", help="Record actions without touching Signal")
    parser.add_argument("--use-ocr", action="store_true", help="Enable OCR fallback for navigation")
    parser.add_argument("--attachment-wait-seconds", type=float, default=10.0, help="Seconds to wait for a saved file to appear")
    parser.add_argument("--max-attachments-per-conversation", type=int, default=9999, help="Upper bound on attachment saves per conversation")
    parser.add_argument("--scan-order", choices=["shortcut-first", "signal-first", "config-first"], default="shortcut-first", help="Conversation traversal order")
    parser.add_argument("--max-conversations", type=int, default=200, help="Maximum visible Signal conversations to scan in signal-first mode")
    parser.add_argument("--startup-wait-seconds", type=float, default=8.0, help="Seconds to wait for Signal window after launch")
    parser.add_argument("--download-action-timeout-seconds", type=float, default=8.0, help="Seconds to wait for the Download menu/save dialog flow")
    parser.add_argument("--allow-text-fallback-scan", action="store_true", help="Allow raw Text-node scan for conversation labels (usually off)")
    parser.add_argument("--allow-config-fallback", action="store_true", help="Allow fallback to config-first when signal-first finds no processable targets")
    parser.add_argument("--shortcut-slots", type=int, default=9, help="Number of Ctrl+N conversation slots to process in shortcut-first mode")
    parser.add_argument("--context-menu-right-nudge-px", type=int, default=10, help="Pixels to nudge right while activating Download menu item")
    parser.add_argument("--no-require-visible-mouse", action="store_true", help="Allow non-visible click backend when pyautogui is unavailable")
    parser.add_argument("--mouse-move-duration-seconds", type=float, default=0.15, help="Seconds per mouse move step for visible pointer movement")
    parser.add_argument("--targets", default="", help="Comma-separated slug list to limit the run")
    parser.add_argument("--manifest-only", action="store_true", help="Only update markdown from the saved manifest")
    parser.add_argument("--traceback", action="store_true", help="Show full traceback on errors")

    return parser


def build_message_md_argv(args: argparse.Namespace) -> list[str]:
    argv = [sys.argv[0]]
    if args.config_dir:
        argv += ["-c", args.config_dir]
    if args.source_folder:
        argv += ["-s", args.source_folder]
    if args.messages_file:
        argv += ["-f", args.messages_file]
    if args.debug:
        argv.append("-d")
    if args.output_folder:
        argv += ["-o", args.output_folder]
    if args.me:
        argv += ["-m", args.me]
    if args.begin:
        argv += ["-b", args.begin]
    return argv


def configure_logging(log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handlers = [logging.StreamHandler(sys.stdout), logging.FileHandler(log_file, encoding="utf-8")]
    # force=True removes any handlers a previously-imported module (config /
    # message_md) already attached to the root logger. Without it basicConfig is
    # a silent no-op, so our stdout+file handlers never attach and every INFO
    # diagnostic is lost (only default-format WARNINGs leak to stderr).
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
        force=True,
    )


def load_the_config(args: argparse.Namespace) -> config.Config:
    if not args.config_dir:
        raise RuntimeError("Missing config directory. Provide -c/--config-dir or set message_md.config_dir in config.json")
    if not args.me:
        raise RuntimeError("Missing slug. Provide -m/--me or set message_md.me in config.json")

    if not args.source_folder:
        raise RuntimeError("Missing source folder. Provide -s/--source-folder, set message_md.source_folder in config.json, or set DATA_DIR in signal.sh")

    source_path = Path(args.source_folder)
    if not source_path.exists():
        raise RuntimeError(f"Source folder not found: {source_path}")

    messages_path = Path(args.messages_file)
    if not messages_path.is_absolute():
        messages_path = source_path / messages_path
    if not messages_path.exists():
        raise RuntimeError(
            f"Messages file not found: {messages_path}. Use -f/--messages-file and -s/--source-folder or set them in config.json."
        )

    original_argv = sys.argv[:]
    try:
        sys.argv = build_message_md_argv(args)
        the_config = config.Config()
        if not message_md.setup(the_config, markdown.YAML_SERVICE_SIGNAL):
            raise RuntimeError(
                "message_md setup did not complete. Check people.json/groups.json under config_dir and confirm your slug exists."
            )
        the_config.reversed = False
        return the_config
    finally:
        sys.argv = original_argv


def resolve_paths(args: argparse.Namespace, the_config: config.Config) -> AutomationSettings:
    validate_signal_executable(args.signal_exe)

    # An explicit -o/--output-folder must win for where media is saved. Otherwise
    # signal.sh's OUTPUT_DIR (applied earlier to downloads_root) or a cwd default
    # would override it and media would land in the repo instead of -o.
    if not _is_default_arg(args, "output_folder"):
        downloads_root = Path(args.output_folder)
    else:
        downloads_root = Path(args.downloads_root or getattr(the_config, "output_folder", "") or ".")
    raw_state = Path(args.state_file) if args.state_file else downloads_root / "signal_ui_state.json"
    raw_log = Path(args.log_file) if args.log_file else downloads_root / "signal_ui_failures.log"

    state_file = raw_state / "signal_ui_state.json" if (raw_state.exists() and raw_state.is_dir()) else raw_state
    log_file = raw_log / "signal_ui_failures.log" if (raw_log.exists() and raw_log.is_dir()) else raw_log

    if not state_file.suffix:
        state_file = state_file / "signal_ui_state.json"
    if not log_file.suffix:
        log_file = log_file / "signal_ui_failures.log"

    return AutomationSettings(
        signal_exe=args.signal_exe,
        window_title=args.window_title,
        conversation_search_shortcut=parse_shortcut(args.conversation_search_shortcut),
        save_shortcut=parse_shortcut(args.save_shortcut),
        next_item_shortcut=parse_shortcut(args.next_item_shortcut),
        downloads_root=str(downloads_root),
        state_file=str(state_file),
        log_file=str(log_file),
        stop_on_error=args.stop_on_error,
        dry_run=args.dry_run,
        use_ocr=args.use_ocr,
        attachment_wait_seconds=args.attachment_wait_seconds,
        max_attachments_per_conversation=args.max_attachments_per_conversation,
        scan_order=args.scan_order,
        max_conversations=args.max_conversations,
        startup_wait_seconds=args.startup_wait_seconds,
        allow_search_fallback=args.allow_search_fallback,
        download_action_timeout_seconds=args.download_action_timeout_seconds,
        allow_text_fallback_scan=args.allow_text_fallback_scan,
        allow_config_fallback=args.allow_config_fallback,
        shortcut_slots=args.shortcut_slots,
        context_menu_right_nudge_px=args.context_menu_right_nudge_px,
        require_visible_mouse=not args.no_require_visible_mouse,
        mouse_move_duration_seconds=args.mouse_move_duration_seconds,
        me=args.me,
    )


def iter_targets(the_config: config.Config, wanted_targets: set[str] | None = None) -> list[Any]:
    targets = flatten_people(the_config)
    if not wanted_targets:
        return targets
    result: list[Any] = []
    for target in targets:
        slug = getattr(target, "slug", "") or ""
        if slug in wanted_targets:
            result.append(target)
    return result


def process_target(driver: SignalUiDriver, settings: AutomationSettings, state: AutomationState, target: Any, activate_target: bool = True) -> list[MediaRecord]:
    slug = getattr(target, "slug", "unknown") or "unknown"
    aliases = build_target_aliases(target)
    label = aliases[0]
    logging.info("Processing %s (%s)", label, slug)

    existing_records = [record for record in state.data.get("downloads", []) if record.get("slug") == slug]
    resume_from = len(existing_records)

    if settings.dry_run:
        records = build_records_for_target(Path(settings.downloads_root), target, media_count=1)
        for record in records:
            state.add_download(record)
        state.mark_completed(slug)
        state.save()
        return records

    if activate_target:
        driver.activate_target(label, aliases)

    driver.reset_message_scan()
    driver.open_media_view()
    media_dir = ensure_media_folder(Path(settings.downloads_root), slug, create=False)

    # New media workflow:
    #   Ctrl+Shift+M (open_media_view) -> Ctrl+T lands on the first media item ->
    #   Enter opens it in the preview -> Ctrl+S saves -> Left arrow goes to the
    #   previous (older) item. When Left arrow stops moving (we have all media),
    #   the same item saves again, producing a byte-identical duplicate, which we
    #   detect and use as the stop signal. Esc then exits the preview.
    driver.enter_media_tab_and_open_first()

    records: list[MediaRecord] = []
    last_hash: str | None = None
    index = 0
    while index < settings.max_attachments_per_conversation:
        index += 1
        desired_name = build_saved_name(slug, datetime.now().strftime("%Y%m%d_%H%M%S"), index, None)

        saved_path = None
        for attempt in range(1, 4):
            try:
                logging.info("Saving %s media item %d attempt %d", slug, index, attempt)
                saved_path = driver.save_media_preview_item(media_dir, desired_name)
                break
            except TimeoutError as exc:
                logging.warning("Save attempt %d failed for %s item %d: %s", attempt, slug, index, exc)
                if attempt < 3:
                    time.sleep(0.5)
                    continue
                logging.info("No Save dialog for %s item %d; assuming end of media", slug, index)
                break

        if saved_path is None:
            break

        # End-of-media detection: if Left arrow no longer moves, Ctrl+S re-saves
        # the same item. A byte-identical file means we have already captured it.
        try:
            current_hash = file_content_hash(saved_path)
        except Exception:
            current_hash = None
        if current_hash is not None and current_hash == last_hash:
            logging.info("Duplicate media item detected for %s; reached end of media", slug)
            try:
                saved_path.unlink()
            except Exception:
                pass
            break
        last_hash = current_hash

        record = MediaRecord(
            slug=slug,
            label=label,
            media_kind="image",
            source_label=Path(desired_name).stem,
            saved_filename=saved_path.name,
            saved_path=str(saved_path),
            markdown_target=f"media/{saved_path.name}",
        )
        records.append(record)
        state.add_download(record)
        state.save()

        # Move to the previous (older) media item for the next save.
        try:
            driver.previous_media_item()
        except Exception:
            break

    # Leave the media preview cleanly before moving to the next conversation.
    try:
        driver.exit_media_preview()
    except Exception:
        pass

    changed = update_markdown_files(Path(settings.downloads_root), slug, records)
    if changed:
        logging.info("Updated %d markdown files for %s", len(changed), slug)

    state.mark_completed(slug)
    state.save()
    return records


def process_signal_first(driver: SignalUiDriver, settings: AutomationSettings, state: AutomationState, targets: list[Any]) -> int:
    labels = driver.get_visible_conversation_labels(settings.max_conversations)
    if not labels:
        logging.warning("No visible Signal conversations found")
        return 0

    logging.info("Signal-first scan found %d visible conversation labels", len(labels))

    target_index = build_target_index(targets)
    processed = 0

    for label in labels:
        target = resolve_target_for_conversation(label, target_index)
        if target is None:
            logging.info("Skipping unmatched conversation '%s'", label)
            continue

        slug = getattr(target, "slug", "unknown") or "unknown"
        if slug in set(state.data.get("completed", [])):
            logging.info("Skipping completed target %s", slug)
            continue

        try:
            process_target(driver, settings, state, target)
            processed += 1
        except Exception as exc:
            logging.exception("Failed processing %s from conversation '%s'", slug, label)
            state.mark_failed(slug, str(exc))
            state.save()
            if settings.stop_on_error:
                return processed

    return processed


def process_shortcut_first(driver: SignalUiDriver, settings: AutomationSettings, state: AutomationState, targets: list[Any]) -> int:
    if not targets:
        logging.warning("No configured targets to process in shortcut-first mode")
        return 0

    processed = 0
    slots = min(settings.shortcut_slots, len(targets), 10)
    logging.info("Shortcut-first mode processing %d conversation slots (Ctrl+1..Ctrl+%d)", slots, slots)

    # Warm up focus so the very first Ctrl+1 is not lost while Signal is still
    # coming to the foreground.
    try:
        driver.connect()
        driver._bring_to_foreground()
        time.sleep(0.6)
    except Exception:
        pass

    target_index = build_target_index(targets)
    logging.info("Known conversation aliases: %s", sorted(target_index.keys()))

    previous_title_norm = None

    for idx in range(1, slots + 1):
        slug = "unknown"

        try:
            logging.info("Opening conversation slot %d with Ctrl+%d", idx, idx)
            driver.open_conversation_by_shortcut(idx)

            # Identify the conversation ONLY from the visible header name. Never
            # guess from config order, so media is never saved under the wrong
            # person.
            title = driver.get_current_conversation_title()
            logging.info("Slot %d: read conversation header title = %r", idx, title)
            if not title:
                logging.warning("Slot %d: could not read the conversation name; skipping this slot", idx)
                continue

            # If this slot shows the same conversation as the previous one, the
            # Ctrl+N index has run past the end of the list (it stays on the last
            # conversation), so we are done.
            title_norm = normalize_text(title)
            if previous_title_norm is not None and title_norm == previous_title_norm:
                logging.info(
                    "Slot %d shows the same conversation as the previous slot (%r); reached the last conversation, stopping",
                    idx, title,
                )
                # Leave the UI tidy: clear the leftover Ctrl+A text selection.
                try:
                    driver._click_to_deselect()
                except Exception:
                    logging.exception("Final deselect click failed")
                break
            previous_title_norm = title_norm

            if normalize_text(title) in {"note to self", "notes to self"}:
                if not settings.me:
                    logging.warning("Slot %d is 'Note to Self' but no --me slug is set; skipping", idx)
                    continue
                target = next((t for t in targets if (getattr(t, "slug", "") or "") == settings.me), None)
                if target is None:
                    logging.warning("Slot %d 'Note to Self' but slug %s is not in targets; skipping", idx, settings.me)
                    continue
                slug = settings.me
                logging.info("Slot %d header 'Note to Self' mapped to your slug %s", idx, slug)
            else:
                target = resolve_target_for_conversation(title, target_index)
                if target is None:
                    logging.warning("Slot %d header '%s' did not match any known person; skipping", idx, title)
                    continue
                slug = getattr(target, "slug", "unknown") or "unknown"
                logging.info("Slot %d header '%s' matched person %s", idx, title, slug)

            if slug in set(state.data.get("completed", [])):
                logging.info("Skipping completed target %s", slug)
                continue

            process_target(driver, settings, state, target, activate_target=False)
            processed += 1
        except Exception as exc:
            logging.exception("Failed processing %s from shortcut slot %d", slug, idx)
            state.mark_failed(slug, str(exc))
            state.save()
            if settings.stop_on_error:
                return processed

    return processed


def process_config_first(driver: SignalUiDriver, settings: AutomationSettings, state: AutomationState, targets: list[Any]) -> int:
    processed = 0
    for target in targets:
        slug = getattr(target, "slug", "unknown") or "unknown"
        if slug in set(state.data.get("completed", [])):
            logging.info("Skipping completed target %s", slug)
            continue
        try:
            process_target(driver, settings, state, target)
            processed += 1
        except Exception as exc:
            logging.exception("Failed processing %s", slug)
            state.mark_failed(slug, str(exc))
            state.save()
            if settings.stop_on_error:
                return processed
    return processed


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    args = apply_json_config(args)
    args = infer_from_signal_sh(args)
    args = infer_common_defaults(args)

    if args.manifest_only and (not args.config_dir or not args.me):
        downloads_root = Path(args.downloads_root or ".")
        state_path = Path(args.state_file or downloads_root / "signal_ui_state.json")
        state = AutomationState(state_path)
        state.load()
        all_records = [MediaRecord(**record) for record in state.data.get("downloads", [])]
        grouped: dict[str, list[MediaRecord]] = {}
        for record in all_records:
            grouped.setdefault(record.slug, []).append(record)
        for slug, records in grouped.items():
            update_markdown_files(downloads_root, slug, records)
        state.save()
        return 0

    the_config = load_the_config(args)
    settings = resolve_paths(args, the_config)
    configure_logging(Path(settings.log_file))

    if not settings.dry_run and not args.manifest_only:
        validate_ui_runtime(settings)

    state = AutomationState(Path(settings.state_file))
    state.load()

    wanted_targets = {slug.strip() for slug in args.targets.split(',') if slug.strip()} or None
    targets = iter_targets(the_config, wanted_targets)

    driver = SignalUiDriver(settings)
    if not settings.dry_run and not args.manifest_only:
        driver.ensure_running()

    if args.manifest_only:
        all_records = [MediaRecord(**record) for record in state.data.get("downloads", [])]
        grouped: dict[str, list[MediaRecord]] = {}
        for record in all_records:
            grouped.setdefault(record.slug, []).append(record)
        for slug, records in grouped.items():
            update_markdown_files(Path(settings.downloads_root), slug, records)
        state.save()
        return 0

    if settings.scan_order == "shortcut-first" and not settings.dry_run:
        processed = process_shortcut_first(driver, settings, state, targets)
        if processed == 0 and settings.allow_config_fallback:
            logging.warning("Shortcut-first mode did not process any targets; falling back to config-first mode")
            process_config_first(driver, settings, state, targets)
        elif processed == 0:
            logging.warning(
                "Shortcut-first mode processed 0 targets. Not falling back to config-first unless --allow-config-fallback is set."
            )
    elif settings.scan_order == "signal-first" and not settings.dry_run:
        processed = process_signal_first(driver, settings, state, targets)
        if processed == 0 and settings.allow_config_fallback:
            logging.warning("Signal-first mode did not process any targets; falling back to config-first mode")
            process_config_first(driver, settings, state, targets)
        elif processed == 0:
            logging.warning(
                "Signal-first mode processed 0 targets. Not falling back to config-first unless --allow-config-fallback is set."
            )
    else:
        process_config_first(driver, settings, state, targets)

    try:
        state.save()
    except Exception as exc:
        logging.error("Final state save failed: %s", exc)
    return 0


def _run_entrypoint() -> int:
    try:
        return main()
    except KeyboardInterrupt:
        logging.error("Interrupted by user")
        return 130
    except Exception as exc:
        # Keep user output concise unless traceback is explicitly requested.
        show_traceback = "--traceback" in sys.argv
        if show_traceback:
            raise
        logging.error("%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(_run_entrypoint())