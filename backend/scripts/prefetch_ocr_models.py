#!/usr/bin/env python3
"""Download configured PaddleOCR models once before an offline deployment."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paddleocr import PaddleOCR

from app.config import get_settings
from app.extraction import _ocr_languages


def main() -> None:
    settings = get_settings()
    for language in _ocr_languages(settings.paddleocr_language):
        PaddleOCR(
            lang=language,
            ocr_version=settings.paddleocr_version,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
        print(f"PaddleOCR model ready: {language} ({settings.paddleocr_version})")


if __name__ == "__main__":
    main()
