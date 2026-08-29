from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "datasets" / "synthetic"


def test_phase8_dataset_counts_languages_and_hashes() -> None:
    manifest = json.loads((DATASET / "manifest.json").read_text(encoding="utf-8"))
    with (DATASET / "subjects.csv").open(encoding="utf-8") as handle:
        subjects = list(csv.DictReader(handle))
    assert manifest["case_count"] == 20
    assert manifest["subject_count"] == 100
    assert manifest["fir_count"] == 20
    assert set(manifest["languages"]) == {"en", "hi", "kn", "mr"}
    assert len(subjects) == len({item["subject_id"] for item in subjects}) == 100
    assert all(item["is_synthetic"] == "true" for item in subjects)
    assert all(item["legal_status"] == "fictional_subject_not_adjudicated" for item in subjects)
    for item in manifest["files"]:
        payload = (DATASET / "firs" / item["filename"]).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == item["sha256"]
        assert b"SYNTHETIC DATASET" in payload
