#!/usr/bin/env python3
"""Capture thesis screenshots from the mock dashboard demo databank.

This refreshes the web UI figures used in the thesis from `mock_dashboard_demo.db`
and applies lightweight post-processing:
- consistent viewport-based crops
- targeted blurring of visible file-path rows
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageFilter
from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
THESIS_DIR = ROOT / "Efficient Data Access and Storage Optimization for PET:CT Imaging Data"
OUTPUT_DIR = THESIS_DIR / "figures" / "screenshots"
DB_PATH = ROOT / "Databanks" / "mock_dashboard_demo.db"
DB_NAME = DB_PATH.name
BASE_URL = os.environ.get("THESIS_SCREENSHOT_BASE_URL", "http://127.0.0.1:5002")

VIEWPORT = {"width": 1726, "height": 1084}
FRAME_SIZE = {"width": 1600, "height": 900}


def ensure_mock_db() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"Mock databank not found: {DB_PATH}")


def pick_study_uid() -> str:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            """
            SELECT study_instance_uid
            FROM dicom_metadata
            WHERE modality = 'PT'
            ORDER BY patient_id
            LIMIT 1
            """
        ).fetchone()
    if not row:
        raise SystemExit("No PT study found in mock_dashboard_demo.db")
    return row[0]


def go(page: Page, url: str, wait_ms: int = 1500) -> None:
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(wait_ms)


def clip(x: int, y: int, width: int, height: int) -> dict[str, int]:
    return {"x": x, "y": y, "width": width, "height": height}


def save_clip(page: Page, path: Path, region: dict[str, int]) -> None:
    page.screenshot(path=str(path), clip=region)


def blur_regions(image_path: Path, regions: Iterable[tuple[int, int, int, int]], radius: int = 10) -> None:
    with Image.open(image_path) as image:
        for left, top, right, bottom in regions:
            box = (
                max(0, int(left)),
                max(0, int(top)),
                min(image.width, int(right)),
                min(image.height, int(bottom)),
            )
            if box[2] <= box[0] or box[3] <= box[1]:
                continue
            blurred = image.crop(box).filter(ImageFilter.GaussianBlur(radius))
            image.paste(blurred, box)
        image.save(image_path)


def padded_bbox(page: Page, selector: str, pad_x: int = 12, pad_y: int = 8) -> tuple[int, int, int, int] | None:
    locator = page.locator(selector).first
    if locator.count() == 0:
        return None
    bbox = locator.bounding_box()
    if not bbox:
        return None
    left = int(bbox["x"] - pad_x)
    top = int(bbox["y"] - pad_y)
    right = int(bbox["x"] + bbox["width"] + pad_x)
    bottom = int(bbox["y"] + bbox["height"] + pad_y)
    return (left, top, right, bottom)


def save_frame(page: Page, path: Path, x: int = 0, y: int = 0) -> None:
    save_clip(page, path, clip(x, y, FRAME_SIZE["width"], FRAME_SIZE["height"]))


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(value, high))


def blur_first_matching_row(
    page: Page,
    image_path: Path,
    frame_x: int,
    frame_y: int,
    selectors: Iterable[str],
) -> None:
    for selector in selectors:
        row = padded_bbox(page, selector)
        if not row:
            continue
        blur_regions(
            image_path,
            [(
                row[0] - frame_x,
                row[1] - frame_y,
                row[2] - frame_x,
                row[3] - frame_y,
            )],
        )
        return


def main() -> None:
    ensure_mock_db()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    study_uid = pick_study_uid()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=1)

        # Index overview
        go(page, f"{BASE_URL}/?db={DB_NAME}&lang=en")
        save_frame(page, OUTPUT_DIR / "ui_index_overview.png", 60, 80)

        # Filtered index with open filter controls
        go(page, f"{BASE_URL}/?db={DB_NAME}&lang=en&modality=PT&manufacturer=Siemens")
        save_frame(page, OUTPUT_DIR / "ui_index_filtered.png", 60, 80)

        # Dashboard overview
        go(page, f"{BASE_URL}/dashboard?db={DB_NAME}&lang=en", wait_ms=2500)
        page.evaluate("document.body.style.zoom = '0.9'")
        page.wait_for_timeout(400)
        save_frame(page, OUTPUT_DIR / "ui_dashboard_overview.png", 40, 120)
        save_frame(page, OUTPUT_DIR / "ui_dashboard.png", 40, 120)

        # Dashboard QA card
        page.locator("h2", has_text="Metadata Completeness").first.scroll_into_view_if_needed()
        page.wait_for_timeout(800)
        save_frame(page, OUTPUT_DIR / "ui_dashboard_qa.png", 70, 130)

        # Study detail overview
        go(page, f"{BASE_URL}/study/{study_uid}?db={DB_NAME}&lang=en", wait_ms=1800)
        save_frame(page, OUTPUT_DIR / "ui_study_detail_overview.png", 70, 90)

        # Expanded study detail with blurred file path row
        page.mouse.wheel(0, 1450)
        page.wait_for_timeout(400)
        page.locator(".expandable").first.click()
        page.wait_for_timeout(700)
        expanded_path = OUTPUT_DIR / "ui_study_detail_expanded.png"
        expanded_x = 70
        expanded_y = 90
        save_frame(page, expanded_path, expanded_x, expanded_y)
        blur_first_matching_row(
            page,
            expanded_path,
            expanded_x,
            expanded_y,
            ("tr:has-text('Absolute Path')", "tr:has-text('Absolute File Path')"),
        )

        # Focused series details panel
        panel = page.locator(".detail-panel").first
        panel.scroll_into_view_if_needed()
        page.wait_for_timeout(400)
        panel_bbox = panel.bounding_box()
        if not panel_bbox:
            raise SystemExit("Could not locate detail panel")
        panel_path = OUTPUT_DIR / "ui_series_details_panel.png"
        panel_x = clamp(
            int(panel_bbox["x"] + (panel_bbox["width"] / 2) - (FRAME_SIZE["width"] / 2)),
            0,
            VIEWPORT["width"] - FRAME_SIZE["width"],
        )
        panel_y = clamp(
            int(panel_bbox["y"] - 80),
            0,
            VIEWPORT["height"] - FRAME_SIZE["height"],
        )
        save_frame(page, panel_path, panel_x, panel_y)
        blur_first_matching_row(
            page,
            panel_path,
            panel_x,
            panel_y,
            (
                ".detail-panel tr:has-text('Absolute File Path')",
                ".detail-panel tr:has-text('Absolute Path')",
            ),
        )

        # Export modal with current controls
        page.locator("#export-csv-button").click()
        page.wait_for_timeout(500)
        save_frame(page, OUTPUT_DIR / "ui_study_export_modal.png", 60, 90)

        browser.close()


if __name__ == "__main__":
    main()
