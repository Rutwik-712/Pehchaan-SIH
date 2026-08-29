from __future__ import annotations

from pathlib import Path
from typing import Tuple
from unicodedata import normalize

from fastapi import HTTPException, status

ALLOWED_EXTENSIONS = {".pdf", ".csv", ".txt", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}


def validate_filename(filename: str) -> Tuple[str, str]:
    normalized = normalize("NFC", filename or "").strip()
    if (
        not normalized
        or len(normalized) > 255
        or "\x00" in normalized
        or "/" in normalized
        or "\\" in normalized
        or normalized in {".", ".."}
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsafe filename")
    suffix = Path(normalized).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported evidence type: {suffix or 'no extension'}",
        )
    return normalized, suffix


def detect_media_type(suffix: str, header: bytes) -> str:
    if suffix == ".pdf" and header.startswith(b"%PDF-"):
        return "application/pdf"
    if suffix == ".png" and header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if suffix in {".jpg", ".jpeg"} and header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if suffix in {".tif", ".tiff"} and (
        header.startswith(b"II*\x00") or header.startswith(b"MM\x00*")
    ):
        return "image/tiff"
    if suffix in {".csv", ".txt"} and b"\x00" not in header:
        try:
            header.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Text evidence must be UTF-8 encoded",
            ) from exc
        return "text/csv" if suffix == ".csv" else "text/plain"
    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail="File content does not match its extension",
    )

