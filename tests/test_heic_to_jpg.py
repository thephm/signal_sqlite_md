import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import heic_to_jpg


class ConvertHeicToJpgTests(unittest.TestCase):
    def make_source(self, directory: Path, name: str = "photo.HEIC") -> Path:
        source = directory / name
        Image.new("RGB", (2, 2), "red").save(source, format="JPEG")
        return source

    def test_converts_and_removes_source_only_after_verification(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = self.make_source(Path(temp_dir))

            result = heic_to_jpg.convert_heic_to_jpg(source)

            self.assertEqual(result.status, "converted")
            self.assertFalse(source.exists())
            self.assertTrue(result.dest_path.exists())
            with Image.open(result.dest_path) as image:
                image.verify()

    def test_existing_destination_is_skipped_without_removing_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = self.make_source(directory)
            destination = directory / "photo.jpg"
            destination.write_bytes(b"existing")

            result = heic_to_jpg.convert_heic_to_jpg(source)

            self.assertEqual(result.status, "skipped_exists")
            self.assertTrue(source.exists())
            self.assertEqual(destination.read_bytes(), b"existing")

    def test_failed_write_keeps_source_and_does_not_replace_destination(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = self.make_source(directory)
            destination = directory / "photo.jpg"
            destination.write_bytes(b"existing")

            with patch("heic_to_jpg.os.replace", side_effect=OSError("rename failed")):
                result = heic_to_jpg.convert_heic_to_jpg(source, force=True)

            self.assertEqual(result.status, "failed")
            self.assertTrue(source.exists())
            self.assertEqual(destination.read_bytes(), b"existing")

    def test_dry_run_does_not_write_or_delete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = self.make_source(Path(temp_dir), "photo.heif")

            result = heic_to_jpg.convert_heic_to_jpg(source, dry_run=True)

            self.assertEqual(result.status, "dry_run")
            self.assertTrue(source.exists())
            self.assertFalse((Path(temp_dir) / "photo.jpg").exists())

    def test_batch_finds_nested_extensions_and_continues_after_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            nested_directory = directory / "nested"
            nested_directory.mkdir()
            valid_source = self.make_source(nested_directory, "valid.HEIF")
            invalid_source = directory / "broken.heic"
            invalid_source.write_bytes(b"not an image")

            summary = heic_to_jpg.convert_heic_files(directory)

            self.assertEqual(summary["converted"], 1)
            self.assertEqual(summary["failed"], 1)
            self.assertEqual(len(summary["failures"]), 1)


if __name__ == "__main__":
    unittest.main()