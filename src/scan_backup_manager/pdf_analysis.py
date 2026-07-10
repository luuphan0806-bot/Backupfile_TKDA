from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader


POINTS_PER_MM = 72 / 25.4
ISO_216_A_SIZES_MM = {
    "A0": (841, 1189),
    "A1": (594, 841),
    "A2": (420, 594),
    "A3": (297, 420),
    "A4": (210, 297),
    "A5": (148, 210),
    "A6": (105, 148),
    "A7": (74, 105),
    "A8": (52, 74),
    "A9": (37, 52),
    "A10": (26, 37),
}
TRACKED_PAPER_CODES = {"A0", "A3", "A4"}
DIMENSION_TOLERANCE = 0.08
AREA_TOLERANCE = 0.35
ASPECT_TOLERANCE = 0.20


@dataclass(slots=True)
class PaperCount:
    pages: int = 0
    files: int = 0


@dataclass(slots=True)
class PdfPaperAnalysis:
    counts: dict[str, PaperCount] = field(default_factory=dict)
    exact_pages: dict[str, int] = field(default_factory=dict)
    unknown_pages: int = 0


def points_to_mm(value: float) -> float:
    return float(value) / POINTS_PER_MM


def _normalized_mm(width_pt: float, height_pt: float) -> tuple[float, float]:
    return tuple(sorted((points_to_mm(width_pt), points_to_mm(height_pt))))  # type: ignore[return-value]


def _score_iso_size(page_mm: tuple[float, float], target_mm: tuple[int, int]) -> tuple[float, bool]:
    short, long = page_mm
    target_short, target_long = sorted(target_mm)
    short_delta = abs(short - target_short) / target_short
    long_delta = abs(long - target_long) / target_long
    page_area = short * long
    target_area = target_short * target_long
    area_delta = abs(page_area - target_area) / target_area
    aspect_delta = abs((long / short) - (target_long / target_short)) / (target_long / target_short)
    exact_match = short_delta <= DIMENSION_TOLERANCE and long_delta <= DIMENSION_TOLERANCE
    practical_match = area_delta <= AREA_TOLERANCE and aspect_delta <= ASPECT_TOLERANCE
    score = min(max(short_delta, long_delta), area_delta + aspect_delta)
    return score, exact_match or practical_match


def classify_pdf_page(width_pt: float, height_pt: float) -> str | None:
    page_mm = _normalized_mm(width_pt, height_pt)
    matches: list[tuple[float, str]] = []
    for code, target_mm in ISO_216_A_SIZES_MM.items():
        score, matched = _score_iso_size(page_mm, target_mm)
        if matched:
            matches.append((score, code))
    if matches:
        return min(matches)[1]
    return None


def _iso_area(code: str) -> int:
    width, height = ISO_216_A_SIZES_MM[code]
    return width * height


def display_bucket_for_iso_code(code: str) -> str:
    """Map exact ISO 216 sizes to the 3 operational mapfile buckets.

    Display rule: A4 and smaller count as A4; pages larger than 150% of A4
    count as A3; pages larger than 150% of A3 count as A0.
    """
    area = _iso_area(code)
    if area <= _iso_area("A4") * 1.5:
        return "A4"
    if area <= _iso_area("A3") * 1.5:
        return "A3"
    return "A0"


def analyze_pdf_paper_counts(path: Path) -> PdfPaperAnalysis:
    reader = PdfReader(str(path))
    counts = {code: PaperCount() for code in TRACKED_PAPER_CODES}
    seen_buckets: set[str] = set()
    exact_pages: dict[str, int] = {}
    unknown_pages = 0
    for page in reader.pages:
        box = page.cropbox or page.mediabox
        code = classify_pdf_page(float(box.width), float(box.height))
        if not code:
            unknown_pages += 1
            continue
        exact_pages[code] = exact_pages.get(code, 0) + 1
        bucket_code = display_bucket_for_iso_code(code)
        counts[bucket_code].pages += 1
        seen_buckets.add(bucket_code)
    for code in seen_buckets:
        counts[code].files = 1
    return PdfPaperAnalysis(
        counts=counts,
        exact_pages=exact_pages,
        unknown_pages=unknown_pages,
    )
