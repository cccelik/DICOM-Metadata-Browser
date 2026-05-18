import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import py7zr

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
        with webui.PROCESS_JOBS_LOCK:
            webui.PROCESS_JOBS.clear()
        with webui.EXTRACT_PROCESS_JOBS_LOCK:
            webui.EXTRACT_PROCESS_JOBS.clear()
        with webui.ANALYSIS_JOBS_LOCK:
            webui.ANALYSIS_JOBS.clear()

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
                insert_progress_callback = kwargs.get("insert_progress_callback")
                kwargs["parse_start_callback"](2)
                for _ in range(2):
                    progress_callback({})
                kwargs["insert_start_callback"](2)
                for _ in range(2):
                    insert_progress_callback({})
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
            self.assertEqual(events[0]["total"], 5)
            phases = [event["phase"] for event in events]
            self.assertIn("Candidate finding", phases)
            self.assertIn("Parsing", phases)
            self.assertIn("Insertion", phases)
            self.assertIn("Finalizing", phases)
            insertion_events = [event for event in events if event["phase"] == "Insertion"]
            self.assertTrue(insertion_events)
            self.assertLess(insertion_events[-1]["percent"], 100.0)
            self.assertEqual(events[-1]["percent"], 100.0)
            self.assertTrue(events[-1]["done"])
            self.assertEqual(events[-1]["message"], "Processing complete")

    def test_web_extract_job_start_runs_job_and_exposes_progress(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            input_root = base / "input"
            output_root = base / "output"
            input_root.mkdir()

            def fake_extract(input_path, output_path, max_file_bytes=None, progress_callback=None):
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

            def fake_extract(input_path, output_path, max_file_bytes=None, progress_callback=None):
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

    def test_web_extract_job_accepts_zip_input(self):
        captured = {}
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            input_archive = base / "input.zip"
            output_root = base / "output"
            input_archive.write_bytes(b"zip")

            def fake_extract(input_path, output_path, max_file_bytes=None, progress_callback=None):
                captured["input_path"] = input_path
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
                        data={"input_root": str(input_archive), "output_root": str(output_root)},
                    )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(captured["input_path"], input_archive.resolve())

    def test_web_extract_job_passes_max_file_size(self):
        captured = {}
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            input_root = base / "input"
            output_root = base / "output"
            input_root.mkdir()

            def fake_extract(input_path, output_path, max_file_bytes=None, progress_callback=None):
                captured["max_file_bytes"] = max_file_bytes
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
                        data={"input_root": str(input_root), "output_root": str(output_root), "max_file_mb": "25"},
                    )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(captured["max_file_bytes"], 25 * 1024 * 1024)

    def test_web_input_size_analysis_reports_threshold_skips(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "small.dcm").write_bytes(b"x")
            (base / "large.dcm").write_bytes(b"x" * 12)

            response = webui.app.test_client().post(
                "/input-size-analysis",
                data={"input_root": str(base), "max_file_mb": str(10 / 1024 / 1024)},
            )

            payload = response.get_json()
            self.assertEqual(response.status_code, 200)
            self.assertTrue(payload["success"])
            self.assertEqual(payload["analysis"]["candidate_files"], 1)
            self.assertEqual(payload["analysis"]["oversized_dicom_like_files"], 1)

    def test_web_input_size_analysis_accepts_zip(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            archive_path = base / "input.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("small.dcm", b"x")
                archive.writestr("large.dcm", b"x" * 12)

            response = webui.app.test_client().post(
                "/input-size-analysis",
                data={"input_root": str(archive_path), "max_file_mb": str(10 / 1024 / 1024)},
            )

            payload = response.get_json()
            self.assertEqual(response.status_code, 200)
            self.assertTrue(payload["success"])
            self.assertEqual(payload["analysis"]["oversized_dicom_like_files"], 1)

    def test_web_input_size_analysis_accepts_7z(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            archive_path = base / "input.7z"
            with py7zr.SevenZipFile(archive_path, "w") as archive:
                archive.writestr(b"x", "small.dcm")
                archive.writestr(b"x" * 12, "large.dcm")

            response = webui.app.test_client().post(
                "/input-size-analysis",
                data={"input_root": str(archive_path), "max_file_mb": str(10 / 1024 / 1024)},
            )

            payload = response.get_json()
            self.assertEqual(response.status_code, 200)
            self.assertTrue(payload["success"])
            self.assertEqual(payload["analysis"]["oversized_dicom_like_files"], 1)

    def test_web_input_size_analysis_job_reports_progress(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "small.dcm").write_bytes(b"x")
            (base / "large.dcm").write_bytes(b"x" * 12)

            with patch("webui.threading.Thread", ImmediateThread):
                response = webui.app.test_client().post(
                    "/input-size-analysis/start",
                    data={"input_root": str(base), "max_file_mb": str(10 / 1024 / 1024)},
                )

            payload = response.get_json()
            self.assertEqual(response.status_code, 200)
            self.assertTrue(payload["success"])
            job_response = webui.app.test_client().get(f"/input-size-analysis/jobs/{payload['job_id']}")
            job_payload = job_response.get_json()
            self.assertEqual(job_response.status_code, 200)
            self.assertTrue(job_payload["success"])
            self.assertEqual(job_payload["job"]["status"], "done")
            self.assertEqual(job_payload["job"]["progress"]["percent"], 100.0)
            self.assertEqual(job_payload["job"]["result"]["oversized_dicom_like_files"], 1)

    def test_web_process_job_can_be_cancelled(self):
        with webui.PROCESS_JOBS_LOCK:
            webui.PROCESS_JOBS["job-1"] = {"id": "job-1", "status": "running"}

        response = webui.app.test_client().post("/process-dicom/cancel/job-1")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])
        with webui.PROCESS_JOBS_LOCK:
            self.assertTrue(webui.PROCESS_JOBS["job-1"]["cancel_requested"])

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

    def test_web_process_job_start_runs_job_and_exposes_progress(self):
        captured = {}
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            input_root = base / "dicoms"
            input_root.mkdir()

            def fake_process_directory(dicom_dir, **kwargs):
                captured["dicom_dir"] = dicom_dir
                captured["kwargs"] = kwargs
                kwargs["progress_callback"](
                    {
                        "phase": "Processing",
                        "current": 1,
                        "total": 2,
                        "percent": 50.0,
                        "elapsed": "00:01",
                        "eta": "00:01",
                        "memory_mb": 20.5,
                        "message": "Processing",
                        "done": False,
                        "error": None,
                    }
                )

            with patch("webui.threading.Thread", ImmediateThread):
                with patch("webui.process_directory", side_effect=fake_process_directory):
                    response = webui.app.test_client().post(
                        "/process-dicom/start",
                        data={
                            "input_root": str(input_root),
                            "db": "processed.db",
                            "process_subdirs": "on",
                            "skip_existing_paths": "on",
                            "max_workers": "2",
                            "max_file_mb": "25",
                            "partial_read_oversized": "on",
                            "partial_read_mb": "3",
                        },
                    )

            payload = response.get_json()
            self.assertEqual(response.status_code, 200)
            self.assertTrue(payload["success"])
            self.assertEqual(captured["dicom_dir"], str(input_root.resolve()))
            self.assertEqual(captured["kwargs"]["db_path"], webui.resolve_db_path("processed.db"))
            self.assertTrue(captured["kwargs"]["process_subdirs"])
            self.assertTrue(captured["kwargs"]["skip_existing_paths"])
            self.assertEqual(captured["kwargs"]["max_workers"], 2)
            self.assertFalse(captured["kwargs"]["auto_workers"])
            self.assertEqual(captured["kwargs"]["max_file_bytes"], 25 * 1024 * 1024)
            self.assertTrue(captured["kwargs"]["partial_read_oversized"])
            self.assertEqual(captured["kwargs"]["partial_read_limit_bytes"], 3 * 1024 * 1024)

            jobs_response = webui.app.test_client().get("/process-dicom/jobs")
            jobs_payload = jobs_response.get_json()
            self.assertTrue(jobs_payload["success"])
            self.assertEqual(len(jobs_payload["jobs"]), 1)
            job = jobs_payload["jobs"][0]
            self.assertEqual(job["status"], "done")
            self.assertEqual(job["db_name"], "processed.db")
            self.assertEqual(job["progress"]["percent"], 100.0)
            self.assertEqual(job["progress"]["memory_mb"], 20.5)

    def test_web_extract_and_process_job_runs_both_steps(self):
        captured = {}
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            input_root = base / "dicoms"
            output_root = base / "samples"
            input_root.mkdir()

            def fake_extract(input_path, output_path, max_file_bytes=None, progress_callback=None):
                captured["extract_input"] = input_path
                captured["extract_output"] = output_path
                progress_callback(
                    {
                        "phase": "Copying",
                        "current": 1,
                        "total": 1,
                        "percent": 100.0,
                        "elapsed": "00:01",
                        "eta": "00:00",
                        "memory_mb": 10.0,
                        "message": "Copied 1 series samples",
                        "done": True,
                        "error": None,
                    }
                )
                return {
                    "copied": 1,
                    "series": 1,
                    "output_root": str(output_path),
                    "elapsed_s": 1.0,
                }

            def fake_process_directory(dicom_dir, **kwargs):
                captured["process_dir"] = dicom_dir
                captured["process_kwargs"] = kwargs
                kwargs["progress_callback"](
                    {
                        "phase": "Processing",
                        "current": 1,
                        "total": 1,
                        "percent": 100.0,
                        "elapsed": "00:01",
                        "eta": "00:00",
                        "memory_mb": 11.0,
                        "message": "Processing complete",
                        "done": True,
                        "error": None,
                    }
                )

            with patch("webui.threading.Thread", ImmediateThread):
                with patch("webui.extract_one_per_series", side_effect=fake_extract):
                    with patch("webui.process_directory", side_effect=fake_process_directory):
                        response = webui.app.test_client().post(
                            "/extract-and-process/start",
                            data={
                                "input_root": str(input_root),
                                "output_root": str(output_root),
                                "db": "combined.db",
                                "process_subdirs": "on",
                                "max_file_mb": "25",
                                "partial_read_oversized": "on",
                                "partial_read_mb": "3",
                            },
                        )

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["success"])
        self.assertEqual(captured["extract_input"], input_root.resolve())
        self.assertEqual(captured["extract_output"], output_root.resolve())
        self.assertEqual(captured["process_dir"], str(output_root.resolve()))
        self.assertEqual(captured["process_kwargs"]["db_path"], webui.resolve_db_path("combined.db"))
        self.assertEqual(captured["process_kwargs"]["partial_read_limit_bytes"], 3 * 1024 * 1024)

        jobs_payload = webui.app.test_client().get("/extract-and-process/jobs").get_json()
        self.assertTrue(jobs_payload["success"])
        self.assertEqual(len(jobs_payload["jobs"]), 1)
        job = jobs_payload["jobs"][0]
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["db_name"], "combined.db")
        self.assertTrue(job["result"]["processed"])
        self.assertEqual(job["progress"]["percent"], 100.0)
        self.assertIn("extract_elapsed", job["progress"])
        self.assertIn("process_elapsed", job["progress"])
        self.assertIn("total_elapsed", job["progress"])

    def test_web_process_job_start_validates_paths_and_workers(self):
        client = webui.app.test_client()
        missing_response = client.post(
            "/process-dicom/start",
            data={"input_root": "/does/not/exist", "db": "x.db"},
        )
        self.assertEqual(missing_response.status_code, 400)
        self.assertFalse(missing_response.get_json()["success"])

        with tempfile.TemporaryDirectory() as td:
            input_root = Path(td) / "dicoms"
            input_root.mkdir()
            workers_response = client.post(
                "/process-dicom/start",
                data={
                    "input_root": str(input_root),
                    "db": "x.db",
                    "max_workers": "0",
                },
            )

        self.assertEqual(workers_response.status_code, 400)
        self.assertFalse(workers_response.get_json()["success"])

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
