import unittest
import os
from io import StringIO
from unittest.mock import patch

from dicom_browser.progress import ProgressTracker, TerminalProgress, format_duration


class TtyStringIO(StringIO):
    def isatty(self):
        return True


class ProgressTests(unittest.TestCase):
    def test_format_duration(self):
        self.assertEqual(format_duration(None), "--:--")
        self.assertEqual(format_duration(-1), "--:--")
        self.assertEqual(format_duration(0), "00:00")
        self.assertEqual(format_duration(65), "01:05")
        self.assertEqual(format_duration(3661), "1:01:01")

    def test_progress_tracker_emits_percent_eta_elapsed_and_memory(self):
        events = []
        tracker = ProgressTracker(total=4, phase="Testing", callback=events.append)

        tracker.emit()
        tracker.update(advance=1, message="one")
        tracker.update(4)
        tracker.finish("done")

        self.assertEqual(events[0]["percent"], 0.0)
        self.assertEqual(events[1]["current"], 1)
        self.assertEqual(events[1]["total"], 4)
        self.assertEqual(events[1]["message"], "one")
        self.assertGreaterEqual(events[1]["percent"], 25.0)
        self.assertIn("elapsed", events[1])
        self.assertIn("eta", events[1])
        self.assertIn("memory_mb", events[1])
        self.assertTrue(events[-1]["done"])
        self.assertEqual(events[-1]["percent"], 100.0)

    def test_terminal_progress_keeps_rendered_line_within_terminal_width(self):
        stream = TtyStringIO()
        progress = TerminalProgress(
            "extract_one_per_series",
            width=30,
            stream=stream,
            min_interval_s=0,
        )
        payload = {
            "phase": "Copying",
            "current": 4559,
            "total": 4560,
            "percent": 99.98,
            "eta": "00:00",
            "elapsed": "00:16",
            "memory_mb": 73.3,
            "done": False,
        }

        with patch("dicom_browser.progress.shutil.get_terminal_size", return_value=os.terminal_size((80, 24))):
            progress(payload)

        rendered = stream.getvalue().split("\r")[-1]
        self.assertLessEqual(len(rendered), 79)
        self.assertNotIn("\n", rendered)


if __name__ == "__main__":
    unittest.main()
