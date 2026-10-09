"""Recurring attachment names (e.g. "Spelling Bee Hints.jpg") get the message's
sent date appended, in both the converter and the UI media download tool."""

import csv
import hashlib
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import signal_ui_automation as sua  # also puts ../hal and ../message_md on sys.path
import attachments

BEE = "Spelling Bee Hints.jpg"


def sent_ms(text: str) -> str:
    """Local 'YYYY-MM-DD HH:MM' -> Signal sentAt milliseconds."""
    return str(int(datetime.strptime(text, "%Y-%m-%d %H:%M").timestamp() * 1000))


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ConverterNamingTests(unittest.TestCase):
    def test_uses_sent_date_not_run_date(self):
        # Sent late on Oct 7 and processed on Oct 8 must still be Oct 7.
        self.assertEqual(
            attachments.apply_filename_exceptions(BEE, sent_ms("2026-10-07 21:47")),
            "Spelling Bee Hints 2026-10-07.jpg",
        )

    def test_match_is_case_insensitive(self):
        self.assertEqual(
            attachments.apply_filename_exceptions("spelling bee HINTS.JPG", sent_ms("2026-10-07 09:00")),
            "spelling bee HINTS 2026-10-07.JPG",
        )

    def test_other_names_unchanged(self):
        self.assertEqual(attachments.apply_filename_exceptions("photo.jpg", sent_ms("2026-10-07 09:00")), "photo.jpg")

    def test_falls_back_to_message_time(self):
        message_time = datetime(2026, 10, 3, 12, 0).timestamp()
        self.assertEqual(
            attachments.apply_filename_exceptions(BEE, "", message_time),
            "Spelling Bee Hints 2026-10-03.jpg",
        )

    def test_no_date_keeps_name(self):
        with self.assertLogs(level="WARNING"):
            self.assertEqual(attachments.apply_filename_exceptions(BEE, ""), BEE)


class UiDownloadNamingTests(unittest.TestCase):
    def run_media_loop(self, saves, csv_rows=(), preexisting=()):
        """Run process_target with a fake Save dialog that writes `saves` in order
        (newest first). Returns (record filenames, files left in media)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source, media = root / "source", root / "media"
            source.mkdir()
            media.mkdir()
            with open(source / attachments.ATTACHMENTS_FILENAME, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["messageId", "sentAt", "plaintextHash", "fileName"])
                writer.writerows(csv_rows)
            for name, data in preexisting:
                (media / name).write_bytes(data)

            settings = sua.AutomationSettings(
                downloads_root=str(root), source_folder=str(source), attachment_wait_seconds=1
            )
            driver = sua.SignalUiDriver(settings)
            queue = list(saves)

            def fake_save_dialog(destination):
                name, data = queue.pop(0)
                if (destination / name).exists():
                    raise RuntimeError(f"Save dialog would prompt to overwrite {name}")
                (destination / name).write_bytes(data)

            driver._handle_windows_save_dialog = fake_save_dialog
            driver._close_all_save_dialogs = lambda: 0
            driver._send_shortcut = lambda keys: True
            for method in ("reset_message_scan", "open_media_view", "enter_media_tab_and_open_first",
                           "previous_media_item", "exit_media_preview", "close_open_panels"):
                setattr(driver, method, lambda *args, **kwargs: None)

            class Target:
                slug, first_name, last_name = "lisa", "Lisa", "Jansen"

            state = sua.AutomationState(root / "state.json")
            with patch.object(sua, "ensure_media_folder", return_value=media), \
                    patch.object(sua, "update_markdown_files", return_value=[]), \
                    patch.object(sua.time, "sleep"):
                records = sua.process_target(driver, settings, state, Target(), activate_target=False)
            return [r.saved_filename for r in records], sorted(p.name for p in media.iterdir())

    def test_sent_date_from_plaintext_hash(self):
        hint = b"hint" * 100
        records, files = self.run_media_loop(
            [(BEE, hint), (BEE, hint)],
            csv_rows=[["m1", sent_ms("2026-10-07 21:47"), sha(hint), BEE]],
        )
        self.assertEqual(records, ["Spelling Bee Hints 2026-10-07.jpg"])
        self.assertEqual(files, ["Spelling Bee Hints 2026-10-07.jpg"])

    def test_replaces_copy_dated_with_run_date(self):
        hint = b"hint" * 100
        records, files = self.run_media_loop(
            [(BEE, hint), (BEE, hint)],
            csv_rows=[["m1", sent_ms("2026-10-07 21:47"), sha(hint), BEE]],
            preexisting=[("Spelling Bee Hints 2026-10-08.jpg", hint)],
        )
        self.assertEqual(files, ["Spelling Bee Hints 2026-10-07.jpg"])

    def test_unknown_hash_uses_older_neighbour_then_newer(self):
        newer, unknown1, older, unknown2 = (bytes([i]) * (500 + i) for i in range(4))
        records, files = self.run_media_loop(
            [("newer.jpg", newer), (BEE, unknown1), ("older.jpg", older), (BEE, unknown2), (BEE, unknown2)],
            csv_rows=[
                ["n", sent_ms("2026-10-07 09:00"), sha(newer), "newer.jpg"],
                ["o", sent_ms("2026-10-05 09:00"), sha(older), "older.jpg"],
            ],
        )
        # unknown1 sits between newer and older: the message above (older) wins.
        # unknown2 is the oldest item: only the message below (older) is known.
        self.assertIn("Spelling Bee Hints 2026-10-05.jpg", files)
        self.assertIn("Spelling Bee Hints 2026-10-05_002.jpg", files)
        self.assertEqual(len(records), 4)
        self.assertFalse(any("undated" in name for name in files))


if __name__ == "__main__":
    unittest.main()
