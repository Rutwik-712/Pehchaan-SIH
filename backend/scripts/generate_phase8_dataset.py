#!/usr/bin/env python3
"""Generate the deterministic, fictional Phase 8 demonstration package."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "datasets" / "synthetic"
CASE_IDS = ["KSP-CR-2048", "KSP-CR-2099"] + [f"KSP-SYN-{index:03d}" for index in range(3, 21)]
FIRST_NAMES = ["Aarav", "Aditi", "Akash", "Ananya", "Arjun", "Bhavna", "Charan", "Deepa", "Dev", "Farah", "Girish", "Harini", "Irfan", "Jaya", "Karan", "Lakshmi", "Manoj", "Nisha", "Omkar", "Pooja"]
LAST_NAMES = ["Rao", "Kumar", "Patil", "Shetty", "Kulkarni"]
LANGUAGES = [
    ("en", "This fictional FIR records a reported association for training and demonstration only."),
    ("hi", "यह काल्पनिक प्राथमिकी केवल प्रशिक्षण और प्रदर्शन के लिए दर्ज की गई है। किसी वास्तविक व्यक्ति से संबंध नहीं है।"),
    ("mr", "ही काल्पनिक प्रथम माहिती अहवाल नोंद केवळ प्रशिक्षण आणि प्रात्यक्षिकासाठी आहे. याचा कोणत्याही वास्तविक व्यक्तीशी संबंध नाही."),
    ("kn", "ಈ ಕಾಲ್ಪನಿಕ ಪ್ರಥಮ ಮಾಹಿತಿ ವರದಿಯನ್ನು ತರಬೇತಿ ಮತ್ತು ಪ್ರದರ್ಶನಕ್ಕಾಗಿ ಮಾತ್ರ ದಾಖಲಿಸಲಾಗಿದೆ. ಇದು ಯಾವುದೇ ನೈಜ ವ್ಯಕ್ತಿಗೆ ಸಂಬಂಧಿಸಿಲ್ಲ."),
]


def main() -> None:
    fir_dir = OUTPUT / "firs"
    fir_dir.mkdir(parents=True, exist_ok=True)
    subjects = []
    cases = []
    files = []
    for case_index, case_id in enumerate(CASE_IDS, start=1):
        language, notice = LANGUAGES[(case_index - 1) % len(LANGUAGES)]
        case_subjects = []
        lines = [
            "SYNTHETIC DATASET — NO REAL PERSONS OR ALLEGATIONS",
            f"FIR: SYN-FIR-{case_index:03d}",
            f"Case: {case_id}",
            f"Language: {language}",
            f"Location: Synthetic Sector {case_index:02d}, Karnataka",
            "Organization: Demonstration Cooperative Society",
            notice,
        ]
        for offset, last_name in enumerate(LAST_NAMES, start=1):
            subject_number = (case_index - 1) * 5 + offset
            first_name = FIRST_NAMES[case_index - 1]
            name = f"{first_name} {last_name} Demo {case_index:02d}"
            phone = f"9{case_index:02d}{offset:02d}{(case_index * 137 + offset * 19) % 100000:05d}"[:10]
            subject_id = f"SYN-SUB-{subject_number:03d}"
            case_subjects.append(subject_id)
            subjects.append({
                "subject_id": subject_id,
                "display_name": name,
                "case_id": case_id,
                "phone": phone,
                "legal_status": "fictional_subject_not_adjudicated",
                "is_synthetic": "true",
            })
            lines.append(f"Person: {name}, Phone: {phone}, associated with the fictional training record.")
        lines.extend([
            "Review note: Every extracted entity and relationship requires human confirmation before graph projection.",
            "Interpretation boundary: This record does not establish guilt, identity, intent, or a basis for enforcement action.",
        ])
        filename = f"SYN-FIR-{case_index:03d}-{language}.txt"
        payload = ("\n".join(lines) + "\n").encode("utf-8")
        path = fir_dir / filename
        path.write_bytes(payload)
        files.append({"case_id": case_id, "filename": filename, "language": language, "sha256": hashlib.sha256(payload).hexdigest(), "subjects": case_subjects})
        cases.append({"case_id": case_id, "fir_id": f"SYN-FIR-{case_index:03d}", "language": language, "subject_count": 5})

    with (OUTPUT / "subjects.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(subjects[0]))
        writer.writeheader(); writer.writerows(subjects)
    (OUTPUT / "cases.json").write_text(json.dumps(cases, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    manifest = {
        "dataset": "threadline-phase8-synthetic-v1",
        "warning": "Entirely fictional. No record may be treated as a real allegation or guilt determination.",
        "case_count": len(cases),
        "subject_count": len(subjects),
        "fir_count": len(files),
        "languages": sorted({item["language"] for item in files}),
        "files": files,
    }
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "cases": len(cases), "subjects": len(subjects), "firs": len(files)}))


if __name__ == "__main__":
    main()
