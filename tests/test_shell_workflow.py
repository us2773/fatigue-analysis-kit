import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash")

EXTRACTOR = """#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ["EXTRACT_LOG"], "a") as stream:
    stream.write(json.dumps(args) + "\\n")
movie = pathlib.Path(args[args.index("-f") + 1])
output = pathlib.Path(args[args.index("-out_dir") + 1])
if os.environ.get("FAIL_EXTRACTION"):
    sys.exit(9)
if not os.environ.get("MISSING_OUTPUT"):
    (output / (movie.stem + ".csv")).write_text("frame\\n1\\n")
"""

DOCKER = """#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys
args = sys.argv[1:]
with open(os.environ["DOCKER_LOG"], "a") as stream:
    stream.write(json.dumps(args) + "\\n")
if "--pipeline=select_movie" in args:
    stage = "selection"
elif "--entrypoint" in args:
    stage = "read_selection"
elif "openface" in args:
    stage = "openface"
else:
    stage = "analysis"
if os.environ.get("FAIL_STAGE") == stage:
    sys.exit(8)
if stage == "selection":
    target = pathlib.Path("data/02_intermediate/movie_list.json")
    target.write_text(os.environ.get("MOVIE_SELECTION", '["selected"]'))
elif stage == "read_selection":
    sys.exit(subprocess.call([sys.executable, "scripts/read_movie_list.py",
                              "data/02_intermediate/movie_list.json"]))
elif stage == "openface":
    sys.exit(subprocess.call(["bash", "scripts/openface.sh",
                              *args[args.index("openface") + 1:]]))
"""


@unittest.skipUnless(os.name == "posix" and BASH, "Requires a Unix Bash environment")
class ShellWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "scripts").mkdir()
        (self.root / "bin").mkdir()
        for path in ("run.sh", "scripts/openface.sh", "scripts/read_movie_list.py"):
            shutil.copyfile(ROOT / path, self.root / path)
        self.data = self.root / "data"
        self.movies = self.data / "01_raw/movie"
        self.temporary = self.data / "02_intermediate/openface_temporary"
        self.results = self.data / "02_intermediate/openface_result"
        for path in (self.movies, self.temporary, self.results):
            path.mkdir(parents=True)
        for name in ("selected", "unrelated"):
            (self.movies / f"{name}.mp4").touch()
        self.extractor = self.root / "bin/extractor"
        self.extractor.write_text(EXTRACTOR)
        self.extractor.chmod(0o755)
        docker = self.root / "bin/docker"
        docker.write_text(DOCKER)
        docker.chmod(0o755)
        self.extract_log = self.root / "extract.log"
        self.docker_log = self.root / "docker.log"
        self.env = {
            **os.environ,
            "PATH": str(self.root / "bin") + os.pathsep + os.environ["PATH"],
            "OPENFACE_DATA_DIR": str(self.data),
            "OPENFACE_BIN": str(self.extractor),
            "EXTRACT_LOG": str(self.extract_log),
            "DOCKER_LOG": str(self.docker_log),
        }

    def run_script(self, script, *args, **env):
        return subprocess.run(
            [BASH, str(self.root / script), *args],
            cwd=self.root, env={**self.env, **env},
            capture_output=True, text=True,
        )

    def log(self, path):
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_explicit_movie_only_and_spaces(self):
        name = "動画 selected"
        (self.movies / f"{name}.mp4").touch()
        (self.temporary / "unrelated.csv").write_text("keep")
        # An explicit request can also regenerate a previously imported result.
        (self.results / f"{name}.parquet").touch()
        result = self.run_script("scripts/openface.sh", name)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.log(self.extract_log)), 1)
        self.assertTrue((self.temporary / f"{name}.csv").exists())
        self.assertEqual((self.temporary / "unrelated.csv").read_text(), "keep")
        self.assertFalse(list(self.temporary.glob(".openface.*")))

    def test_batch_still_skips_completed_movies(self):
        (self.results / "unrelated.parquet").touch()
        result = self.run_script("scripts/openface.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.log(self.extract_log)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0][calls[0].index("-f") + 1].endswith("selected.mp4"))

    def test_failure_or_missing_output_does_not_publish_partial_csv(self):
        for options in ({"FAIL_EXTRACTION": "1"}, {"MISSING_OUTPUT": "1"}):
            with self.subTest(options=options):
                result = self.run_script("scripts/openface.sh", "selected", **options)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.temporary / "selected.csv").exists())
                self.assertFalse(list(self.temporary.glob(".openface.*")))

    def test_rejects_invalid_or_missing_movie(self):
        for name in ("", "../selected", "dir\\selected", "absent"):
            with self.subTest(name=name):
                result = self.run_script("scripts/openface.sh", name)
                self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.extract_log.exists())

    def test_model_flags(self):
        for model in ("static", "dynamic"):
            with self.subTest(model=model):
                result = self.run_script("scripts/openface.sh", "selected", model)
                self.assertEqual(result.returncode, 0, result.stderr)
                args = self.log(self.extract_log)[-1]
                self.assertEqual("-au_static" in args, model == "static")
                self.assertNotIn("-au_dynamic", args)
        self.assertNotEqual(
            self.run_script("scripts/openface.sh", "selected", "unknown").returncode, 0
        )

    def test_analysis_workflow_order(self):
        result = self.run_script("run.sh", "experiment", "analyze")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.log(self.docker_log)
        self.assertEqual(len(calls), 4)
        self.assertIn("--pipeline=select_movie", calls[0])
        self.assertIn("--entrypoint", calls[1])
        self.assertEqual(calls[2][-3:], ["openface", "selected", "static"])
        self.assertIn("--pipeline=analyze", calls[3])
        self.assertNotIn("external_csv", str(calls))
        self.assertEqual(len(self.log(self.extract_log)), 1)

    def test_failed_stage_stops_following_stages(self):
        for stage, expected_calls in (
            ("selection", 1), ("read_selection", 2), ("openface", 3), ("analysis", 4)
        ):
            with self.subTest(stage=stage):
                self.docker_log.unlink(missing_ok=True)
                result = self.run_script("run.sh", "experiment", "analyze", FAIL_STAGE=stage)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(len(self.log(self.docker_log)), expected_calls)

    def test_invalid_selection_stops_before_openface(self):
        result = self.run_script(
            "run.sh", "experiment", "analyze", MOVIE_SELECTION='["first", "second"]'
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.log(self.docker_log)), 2)
        self.assertFalse(self.extract_log.exists())

    def test_batch_workflow_is_preserved(self):
        result = self.run_script("run.sh", "experiment", "ext_v4")
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.log(self.docker_log)
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0][-1], "openface")
        self.assertIn("--pipeline=external_csv", calls[1])
        self.assertIn("--pipeline=ext_v4", calls[2])


if __name__ == "__main__":
    unittest.main()
