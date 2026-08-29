# Phase 8 synthetic demonstration data

This package is entirely fictional. It contains exactly 20 case records, 100 fictional subjects (five per case), and 20 UTF-8 FIR-style files across English, Hindi, Marathi, and Kannada. No record is a real allegation, and `legal_status` deliberately states `fictional_subject_not_adjudicated`.

Generate or verify the deterministic package:

```bash
backend/.venv/bin/python backend/scripts/generate_phase8_dataset.py
backend/.venv/bin/pytest backend/tests/test_phase8_dataset.py -q
```

Load it through the protected API after the stack is healthy:

```bash
backend/.venv/bin/python backend/scripts/load_phase8_dataset.py --auto-review-synthetic
```

The auto-review flag is intentionally explicit and is safe only for this labelled fictional package. Never use it with operational or real-person data. Without the flag, files are uploaded and processed but stay behind the normal human-review gate.
