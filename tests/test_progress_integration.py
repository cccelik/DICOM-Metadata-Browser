import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import process_dicom
import webui


class ImmediateThread:
    def __init__(self, target, args=(), kwargs=None, daemon=None):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}
        self.daemon = daemon

    def start(self):
        self.target(*self.args, **self.kwargs)


class ProgressIntegrationTests(unittest.TestCase):
    def setUp(self):
        with webui.EXTRACT_JOBS_LOCK:
            webui.EXTRACT_JOBS.clear()

    def test_process_directory_reports_progress_when_not_verbose(self):
        events = []
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            scan_dir = base / "scan"
            scan_dir.mkdir()
            dcm_files = [scan_dir / "one.dcm", scan_dir / "two.dcm"]
            for path in dcm_files:
                path.write_bytes(b"x")

            def fake_extract_and_store(*args, **kwargs):
                progress_callback = kwargs.get("progress_callback")
                for _ in range(4):
                    progress_callback({})
                return 0, 0, 0, [], {"extract_metadata_s": 0.01}

            with patch("process_dicom.collect_dicom_files", return_value=dcm_files):
                with patch("process_dicom._extract_and_store", side_effect=fake_extract_and_store):
                    process_dicom.process_directory(
                        str(scan_dir),
                        db_path=str(base / "progress.db"),
                        process_subdirs=False,
                        auto_workers=False,
                        verbose=False,
                        progress_callback=events.append,
                    )

            self.assertTrue(events)
            self.assertEqual(events[0]["total"], 4)
            self.assertEqual(events[-1]["percent"], 100.0)
            self.assertTrue(events[-1]["done"])
            self.assertEqual(events[-1]["message"], "Processing complete")

    def test_web_extract_job_start_runs_job_and_exposes_progress(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            input_root = base / "input"
            output_root = base / "output"
            input_root.mkdir()

            def fake_extract(input_path, output_path, progress_callback=None):
                progress_callback(
                    {
                        "phase": "Copying",
                        "current": 1,
                        "total": 2,
                        "percent": 50.0,
                        "elapsed": "00:01",
                        "eta": "00:01",
                        "memory_mb": 12.5,
                        "message": "Copied 1 series samples",
                        "done": False,
                        "error": None,
                    }
                )
                return {
                    "copied": 2,
                    "series": 2,
                    "output_root": str(output_path),
                    "elapsed_s": 2.0,
                }

            with patch("webui.threading.Thread", ImmediateThread):
                with patch("webui.extract_one_per_series", side_effect=fake_extract):
                    client = webui.app.test_client()
                    response = client.post(
                        "/extract-one-per-series/start",
                        data={
                            "input_root": str(input_root),
                            "output_root": str(output_root),
                        },
                    )

            payload = response.get_json()
            self.assertEqual(response.status_code, 200)
            self.assertTrue(payload["success"])

            jobs_response = webui.app.test_client().get("/extract-one-per-series/jobs")
            jobs_payload = jobs_response.get_json()
            self.assertTrue(jobs_payload["success"])
            self.assertEqual(len(jobs_payload["jobs"]), 1)
            job = jobs_payload["jobs"][0]
            self.assertEqual(job["status"], "done")
            self.assertEqual(job["result"]["copied"], 2)
            self.assertEqual(job["progress"]["percent"], 100.0)
            self.assertEqual(job["progress"]["memory_mb"], 12.5)

    def test_web_extract_job_uses_default_output_when_blank(self):
        captured = {}
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            input_root = base / "input"
            input_root.mkdir()

            def fake_extract(input_path, output_path, progress_callback=None):
                captured["input_path"] = input_path
                captured["output_path"] = output_path
                progress_callback(
                    {
                        "phase": "Copying",
                        "current": 0,
                        "total": 0,
                        "percent": 100.0,
                        "elapsed": "00:00",
                        "eta": "00:00",
                        "memory_mb": 1.0,
                        "message": "Done",
                        "done": True,
                        "error": None,
                    }
                )
                return {
                    "copied": 0,
                    "series": 0,
                    "output_root": str(output_path),
                    "elapsed_s": 0.0,
                }

            with patch("webui.threading.Thread", ImmediateThread):
                with patch("webui.extract_one_per_series", side_effect=fake_extract):
                    response = webui.app.test_client().post(
                        "/extract-one-per-series/start",
                        data={"input_root": str(input_root), "output_root": ""},
                    )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(captured["input_path"], input_root.resolve())
            self.assertEqual(captured["output_path"], webui.ONE_PER_SERIES_OUTPUT_DIR.resolve())

    def test_extract_output_default_display_is_relative(self):
        self.assertEqual(webui.ONE_PER_SERIES_OUTPUT_DISPLAY, "OnePerSeriesSamples")
        self.assertFalse(Path(webui.ONE_PER_SERIES_OUTPUT_DISPLAY).is_absolute())
        self.assertEqual(
            webui.resolve_extract_output_path(webui.ONE_PER_SERIES_OUTPUT_DISPLAY),
            webui.ONE_PER_SERIES_OUTPUT_DIR.resolve(),
        )

    def test_web_extract_job_start_validates_paths(self):
        client = webui.app.test_client()
        response = client.post(
            "/extract-one-per-series/start",
            data={"input_root": "/does/not/exist", "output_root": "/tmp/out"},
        )
        payload = response.get_json()
        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["success"])

    def test_filesystem_directories_lists_subdirectories(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            visible = base / "visible"
            hidden = base / ".hidden"
            visible.mkdir()
            hidden.mkdir()
            (base / "file.txt").write_text("not a directory")

            client = webui.app.test_client()
            response = client.get(
                "/filesystem/directories",
                query_string={"path": str(base)},
            )

            payload = response.get_json()
            self.assertEqual(response.status_code, 200)
            self.assertTrue(payload["success"])
            self.assertEqual(payload["path"], str(base.resolve()))
            self.assertEqual(payload["parent"], str(base.resolve().parent))
            names = [entry["name"] for entry in payload["directories"]]
            self.assertEqual(names, ["visible"])

    def test_filesystem_directories_rejects_missing_directory(self):
        client = webui.app.test_client()
        response = client.get(
            "/filesystem/directories",
            query_string={"path": "/does/not/exist"},
        )

        payload = response.get_json()
        self.assertEqual(response.status_code, 404)
        self.assertFalse(payload["success"])


if __name__ == "__main__":
    unittest.main()
