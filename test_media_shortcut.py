"""Standalone diagnostic for the Ctrl+Shift+M media-view shortcut.

Run it, then click on your Signal Desktop window during the countdown.
It will try several keyboard-delivery methods, one at a time, so we can see
which (if any) actually opens the All Media pane.

Usage:
    py -3 test_media_shortcut.py
"""

from __future__ import annotations

import sys
import time

from signal_ui_automation import send_scancode_shortcut

try:
    import pyautogui
except Exception:
    pyautogui = None

try:
    from pywinauto.keyboard import send_keys
except Exception:
    send_keys = None


def countdown(msg: str, seconds: int = 4) -> None:
    print(f"\n{msg}")
    for remaining in range(seconds, 0, -1):
        print(f"  focus Signal... {remaining}", end="\r", flush=True)
        time.sleep(1)
    print(" " * 40, end="\r")


def method_scancode() -> None:
    print("[1] SendInput scancode: Ctrl+1 then Ctrl+Shift+M")
    print("    Ctrl+1 ->", send_scancode_shortcut(["ctrl", "1"]))
    time.sleep(0.6)
    print("    Ctrl+Shift+M ->", send_scancode_shortcut(["ctrl", "shift", "m"]))


def method_pyautogui_hotkey() -> None:
    if pyautogui is None:
        print("[2] pyautogui unavailable")
        return
    print("[2] pyautogui.hotkey: Ctrl+1 then Ctrl+Shift+M")
    pyautogui.hotkey("ctrl", "1")
    time.sleep(0.6)
    pyautogui.hotkey("ctrl", "shift", "m")


def method_pyautogui_keydown() -> None:
    if pyautogui is None:
        print("[3] pyautogui unavailable")
        return
    print("[3] pyautogui keyDown/keyUp: Ctrl+Shift+M")
    for key in ("ctrl", "shift", "m"):
        pyautogui.keyDown(key)
        time.sleep(0.05)
    for key in ("m", "shift", "ctrl"):
        pyautogui.keyUp(key)
        time.sleep(0.05)


def method_send_keys() -> None:
    if send_keys is None:
        print("[4] pywinauto send_keys unavailable")
        return
    print("[4] pywinauto send_keys: ^+m")
    send_keys("^+m", pause=0.05, with_spaces=True)


def main() -> int:
    methods = [
        ("scancode", method_scancode),
        ("pyautogui.hotkey", method_pyautogui_hotkey),
        ("pyautogui.keyDown", method_pyautogui_keydown),
        ("pywinauto.send_keys", method_send_keys),
    ]

    print("Media-view shortcut diagnostic")
    print("Watch Signal after each method and note which one opens All Media.")

    for name, fn in methods:
        countdown(f"About to test: {name}", seconds=4)
        try:
            fn()
        except Exception as exc:
            print(f"    {name} raised: {exc}")
        time.sleep(2.0)
        input(f"    Did '{name}' open the media pane? Press Enter to continue... ")

    print("\nDone. Tell me which method (if any) opened the pane.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
