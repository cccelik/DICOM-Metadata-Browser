"""Progress helpers shared by CLI scripts and web jobs."""

from __future__ import annotations

import math
import os
import resource
import shutil
import sys
import time
from dataclasses import dataclass
from typing import Callable, Optional


ProgressCallback = Callable[[dict], None]


def format_duration(seconds: Optional[float]) -> str:
    if seconds is None or not math.isfinite(seconds) or seconds < 0:
        return "--:--"
    seconds_int = int(round(seconds))
    minutes, secs = divmod(seconds_int, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _rss_unit_divisor() -> int:
    # macOS reports bytes, Linux reports KiB.
    return 1024 * 1024 if sys.platform == "darwin" else 1024


def current_memory_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return float(usage.ru_maxrss) / _rss_unit_divisor()


@dataclass
class ProgressState:
    phase: str
    current: int
    total: int
    percent: float
    elapsed_s: float
    eta_s: Optional[float]
    memory_mb: float
    message: str = ""
    done: bool = False
    error: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "phase": self.phase,
            "current": self.current,
            "total": self.total,
            "percent": self.percent,
            "elapsed_s": self.elapsed_s,
            "elapsed": format_duration(self.elapsed_s),
            "eta_s": self.eta_s,
            "eta": format_duration(self.eta_s),
            "memory_mb": self.memory_mb,
            "message": self.message,
            "done": self.done,
            "error": self.error,
        }


class ProgressTracker:
    def __init__(
        self,
        total: int,
        phase: str,
        callback: Optional[ProgressCallback] = None,
    ) -> None:
        self.total = max(int(total), 0)
        self.current = 0
        self.phase = phase
        self.message = ""
        self.start_time = time.perf_counter()
        self.callback = callback

    def _state(self, *, done: bool = False, error: Optional[str] = None) -> ProgressState:
        elapsed = time.perf_counter() - self.start_time
        if self.total > 0:
            percent = min(100.0, max(0.0, self.current / self.total * 100.0))
            eta = (elapsed / self.current * (self.total - self.current)) if self.current else None
        else:
            percent = 100.0 if done else 0.0
            eta = None
        return ProgressState(
            phase=self.phase,
            current=self.current,
            total=self.total,
            percent=percent,
            elapsed_s=elapsed,
            eta_s=eta,
            memory_mb=current_memory_mb(),
            message=self.message,
            done=done,
            error=error,
        )

    def emit(self, *, done: bool = False, error: Optional[str] = None) -> dict:
        payload = self._state(done=done, error=error).as_dict()
        if self.callback:
            self.callback(payload)
        return payload

    def update(
        self,
        current: Optional[int] = None,
        *,
        advance: int = 0,
        total: Optional[int] = None,
        phase: Optional[str] = None,
        message: Optional[str] = None,
    ) -> dict:
        if total is not None:
            self.total = max(int(total), 0)
        if phase is not None:
            self.phase = phase
        if message is not None:
            self.message = message
        if current is not None:
            self.current = max(0, int(current))
        elif advance:
            self.current = max(0, self.current + int(advance))
        if self.total:
            self.current = min(self.current, self.total)
        return self.emit()

    def finish(self, message: str = "") -> dict:
        if message:
            self.message = message
        self.current = self.total
        return self.emit(done=True)

    def fail(self, message: str) -> dict:
        self.message = message
        return self.emit(done=True, error=message)


class TerminalProgress:
    def __init__(
        self,
        label: str,
        width: int = 30,
        stream=None,
        min_interval_s: float = 0.08,
    ) -> None:
        self.label = label
        self.width = width
        self.stream = stream or sys.stderr
        self.last_len = 0
        self.enabled = self.stream.isatty()
        self.last_payload: Optional[dict] = None
        self.min_interval_s = min_interval_s
        self.last_render_s = 0.0

    def _terminal_columns(self) -> int:
        try:
            return shutil.get_terminal_size(fallback=(100, 20)).columns
        except OSError:
            return 100

    def _build_line(self, payload: dict) -> str:
        columns = max(40, self._terminal_columns() - 1)
        percent = float(payload.get("percent") or 0.0)
        current = int(payload.get("current") or 0)
        total = int(payload.get("total") or 0)
        phase = str(payload.get("phase") or self.label)
        eta = payload.get("eta") or "--:--"
        elapsed = payload.get("elapsed") or "00:00"
        memory = float(payload.get("memory_mb") or 0.0)
        prefix = f"{self.label}: {phase} "
        suffix = f" {percent:5.1f}% {current}/{total} ETA {eta} elapsed {elapsed} mem {memory:.1f} MB"
        bar_width = max(8, min(self.width, columns - len(prefix) - len(suffix) - 2))
        if bar_width <= 8 and len(prefix) + len(suffix) + bar_width + 2 > columns:
            prefix = f"{phase} "
            suffix = f" {percent:5.1f}% {current}/{total} ETA {eta}"
            bar_width = max(8, min(self.width, columns - len(prefix) - len(suffix) - 2))
        filled = int(round(bar_width * percent / 100.0))
        bar = "#" * filled + "-" * (bar_width - filled)
        line = f"{prefix}[{bar}]{suffix}"
        if len(line) > columns:
            line = line[:columns]
        return line

    def __call__(self, payload: dict) -> None:
        self.last_payload = payload
        if not self.enabled:
            return
        now = time.perf_counter()
        if not payload.get("done") and now - self.last_render_s < self.min_interval_s:
            return
        self.last_render_s = now
        line = self._build_line(payload)
        padding = " " * max(0, self.last_len - len(line))
        self.stream.write("\r" + line + padding)
        self.stream.flush()
        self.last_len = len(line)
        if payload.get("done"):
            self.stream.write(os.linesep)
            self.stream.flush()
            self.last_len = 0

    def print_summary(self, message: str) -> None:
        if self.enabled and self.last_len:
            self.stream.write(os.linesep)
            self.last_len = 0
        print(message)
