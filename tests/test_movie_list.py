import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "read_movie_list", ROOT / "scripts/read_movie_list.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MovieListTests(unittest.TestCase):
    def test_single_name_including_spaces_and_japanese(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "movie_list.json"
            path.write_text(json.dumps(["動画 01"]), encoding="utf-8")
            self.assertEqual(MODULE.read_movie_name(str(path)), "動画 01")

    def test_rejects_empty_multiple_and_non_list_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "movie_list.json"
            for value in ([], ["first", "second"], "first", {"movie": "first"}, None):
                with self.subTest(value=value):
                    path.write_text(json.dumps(value), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        MODULE.read_movie_name(str(path))

    def test_rejects_invalid_names(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "movie_list.json"
            for value in (None, 1, "", ".", "..", "../movie", "dir\\movie", "a\nb", "a\rb", "a\0b"):
                with self.subTest(value=value):
                    path.write_text(json.dumps([value]), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        MODULE.read_movie_name(str(path))

    def test_cli_failure_does_not_print_a_movie(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "movie_list.json"
            path.write_text('["first", "second"]', encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/read_movie_list.py"), str(path)],
                capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")

    def test_cli_reports_missing_and_invalid_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "movie_list.json"
            for content in (None, "[broken"):
                with self.subTest(content=content):
                    if content is not None:
                        path.write_text(content, encoding="utf-8")
                    result = subprocess.run(
                        [sys.executable, str(ROOT / "scripts/read_movie_list.py"), str(path)],
                        capture_output=True, text=True,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
