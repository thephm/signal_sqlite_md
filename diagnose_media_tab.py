"""Interactive diagnostic to pin down which Ctrl+Shift+M delivery opens All Media.

You SAW the media tab appear twice during the automatic run, so some methods
work. This version tests one method at a time and asks you y/N whether the
All Media pane opened, so we learn exactly which one to use in production.

Rules that make the results trustworthy:
  * Between tests it closes the pane with Escape ONLY - never Ctrl+Shift+M - so
    every Ctrl+Shift+M below is a genuine OPEN attempt (no toggle confusion).
  * It never saves anything from Signal (no Ctrl+S).

Usage:
    py -3 diagnose_media_tab.py
(Signal Desktop must be running with a conversation reachable via Ctrl+1.)
"""

from __future__ import annotations

import time

from signal_ui_automation import (
    AutomationSettings,
    SignalUiDriver,
    send_scancode_shortcut,
)

try:
    import pyautogui
except Exception:
    pyautogui = None


def reset_state(driver: SignalUiDriver) -> None:
    """Get a known starting point: Signal focused, conversation 1 open, pane closed."""
    driver._bring_to_foreground()
    time.sleep(0.5)
    driver.open_conversation_by_shortcut(1)
    time.sleep(0.8)
    # Close any leftover All Media pane / preview with Escape (NOT Ctrl+Shift+M).
    send_scancode_shortcut(["escape"])
    time.sleep(0.3)
    send_scancode_shortcut(["escape"])
    time.sleep(0.3)


def prep_selection() -> None:
    """Reproduce the post-name-extraction state: focus last message, select all."""
    send_scancode_shortcut(["ctrl", "j"])
    time.sleep(0.25)
    send_scancode_shortcut(["ctrl", "a"])
    time.sleep(0.25)


def ask(name: str) -> bool:
    ans = input(f"    >>> Did the All Media tab appear for [{name}]? [y/N] ").strip().lower()
    return ans.startswith("y")


# --- individual delivery methods -------------------------------------------

def m_scancode_ctrlj(driver: SignalUiDriver) -> None:
    prep_selection()
    send_scancode_shortcut(["ctrl", "j"])  # deselect
    time.sleep(0.3)
    send_scancode_shortcut(["ctrl", "shift", "m"])


def m_scancode_noselect(driver: SignalUiDriver) -> None:
    prep_selection()
    send_scancode_shortcut(["ctrl", "shift", "m"])  # fire with text still selected


def m_scancode_click(driver: SignalUiDriver) -> None:
    prep_selection()
    try:
        driver._click_to_deselect()
    except Exception as exc:
        print(f"    click failed: {exc}")
    time.sleep(0.3)
    send_scancode_shortcut(["ctrl", "shift", "m"])


def m_pyautogui_hotkey(driver: SignalUiDriver) -> None:
    prep_selection()
    send_scancode_shortcut(["ctrl", "j"])
    time.sleep(0.3)
    if pyautogui is not None:
        pyautogui.hotkey("ctrl", "shift", "m")


def m_pyautogui_hold(driver: SignalUiDriver) -> None:
    prep_selection()
    send_scancode_shortcut(["ctrl", "j"])
    time.sleep(0.3)
    if pyautogui is not None:
        pyautogui.keyDown("ctrl")
        time.sleep(0.08)
        pyautogui.keyDown("shift")
        time.sleep(0.08)
        pyautogui.press("m")
        time.sleep(0.08)
        pyautogui.keyUp("shift")
        pyautogui.keyUp("ctrl")


def m_production(driver: SignalUiDriver) -> None:
    """Run the REAL production path: read the conversation name, then the actual
    open_media_view(). This reproduces exactly what the automation does, so if
    this fails while D succeeds, the problem is in open_media_view's context."""
    driver.get_current_conversation_title()
    driver.reset_message_scan()
    driver.open_media_view()


def _leave_media_panel_open() -> None:
    """Simulate the leftover state at the end of a previous conversation: an
    AllMedia panel is open and NOT closed before moving on."""
    send_scancode_shortcut(["ctrl", "j"])
    time.sleep(0.25)
    if pyautogui is not None:
        pyautogui.hotkey("ctrl", "shift", "m")
    time.sleep(1.2)


def m_prod_carryover_no_fix(driver: SignalUiDriver) -> None:
    """Reproduce prod: previous conversation left a media panel open, then we
    switch conversation WITHOUT closing it and run the real path. Expected to
    FAIL if the leftover panel is the cause."""
    _leave_media_panel_open()
    driver.open_conversation_by_shortcut(1)  # move on, no Escape
    time.sleep(0.8)
    driver.get_current_conversation_title()
    driver.reset_message_scan()
    driver.open_media_view()


def m_prod_carryover_with_fix(driver: SignalUiDriver) -> None:
    """Same carryover, but call close_open_panels() first (the new fix). Should
    OPEN the media tab."""
    _leave_media_panel_open()
    driver.open_conversation_by_shortcut(1)  # move on
    time.sleep(0.8)
    driver.close_open_panels()  # THE FIX
    driver.get_current_conversation_title()
    driver.reset_message_scan()
    driver.open_media_view()


METHODS = [
    ("A: scancode, Ctrl+J deselect (old production method)", m_scancode_ctrlj),
    ("B: scancode, NO deselect (text still selected)", m_scancode_noselect),
    ("C: scancode, mouse-click deselect", m_scancode_click),
    ("D: pyautogui.hotkey, Ctrl+J deselect", m_pyautogui_hotkey),
    ("E: pyautogui keyDown/keyUp hold, Ctrl+J deselect", m_pyautogui_hold),
    ("F: REAL production open_media_view() (name read + open)", m_production),
    ("G: prod carryover, NO panel-close (expected FAIL)", m_prod_carryover_no_fix),
    ("H: prod carryover, WITH close_open_panels() fix (expect OPEN)", m_prod_carryover_with_fix),
]


def main() -> int:
    settings = AutomationSettings(
        window_title="Signal",
        require_visible_mouse=False,
        mouse_move_duration_seconds=0.1,
    )
    driver = SignalUiDriver(settings)
    print("Connecting to Signal Desktop window...")
    driver.connect()
    print("Connected.\n")
    print("Watch Signal after each test and answer y/N. Do not touch the mouse/keyboard.\n")

    results = []
    for name, fn in METHODS:
        print(f"=== {name} ===")
        reset_state(driver)
        try:
            fn(driver)
        except Exception as exc:
            print(f"    method raised: {exc}")
        time.sleep(1.5)
        opened = ask(name)
        results.append((name, opened))
        # Close the pane with Escape only, so the next test starts clean.
        send_scancode_shortcut(["escape"])
        time.sleep(0.4)
        print()

    print("=== SUMMARY ===")
    for name, opened in results:
        print(f"  {'OPENED ' if opened else '  no   '}  {name}")
    winners = [n for n, ok in results if ok]
    if winners:
        print(f"\nUse this delivery in open_media_view: {winners[0]}")
    else:
        print("\nNothing opened this time - re-run; the pane appeared before so a method works.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
