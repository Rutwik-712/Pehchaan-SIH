from __future__ import annotations

import re


GRAPH_ENTITY_TYPES = {
    "PERSON",
    "LOCATION",
    "ORGANIZATION",
    "PHONE_NUMBER",
    "VEHICLE",
    "EMAIL",
}

_RESERVED_VALUES = {
    "allegations",
    "background",
    "case",
    "complaint summary",
    "date",
    "declaration",
    "details",
    "en",
    "english",
    "english/latin",
    "fir",
    "ksp",
    "language",
    "location",
    "name",
    "narrative",
    "observations",
    "organization",
    "page",
    "person",
    "phone",
    "property or identifiers noted",
    "synthetic",
    "summary",
    "undetermined",
    "vehicle",
    "व्यक्ति",
    "यह",
    "याचा",
    "प्रथम",
    "प्रदर्शनासाठी",
    "ವ್ಯಕ್ತಿ",
    "ಪ್ರಥಮ",
    "ಪ್ರದರ್ಶನಕ್ಕಾಗಿ",
}
_CASE_REFERENCE = re.compile(r"\b[A-Z]{2,8}[-/][A-Z]{1,8}[-/]\d{2,}\b", re.I)
_METADATA_WORDS = re.compile(r"\b(?:case\s*(?:id|number|no\.?|reference)?|fir\s*(?:number|no\.?)?|language|classification|jurisdiction)\b", re.I)
_PHONE = re.compile(r"(?:91)?[6-9]\d{9}")
_VEHICLE = re.compile(r"[A-Z]{2}\d{1,2}[A-Z]{1,3}\d{4}", re.I)
_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)


def is_supported_graph_entity(entity_type: str, value: str) -> bool:
    """Keep real-world actors, places, objects and identifiers out of metadata noise."""
    if entity_type not in GRAPH_ENTITY_TYPES or not value:
        return False
    raw = value.strip()
    normalized = re.sub(r"\s+", " ", raw).strip(" .,;:").casefold()
    if not normalized or normalized in _RESERVED_VALUES or "\n" in raw or ":" in raw:
        return False
    if _CASE_REFERENCE.search(raw) or _METADATA_WORDS.search(raw):
        return False
    if entity_type == "PHONE_NUMBER":
        return _PHONE.fullmatch(re.sub(r"\D", "", raw)) is not None
    if entity_type == "VEHICLE":
        return _VEHICLE.fullmatch(re.sub(r"[\s-]", "", raw)) is not None
    if entity_type == "EMAIL":
        return _EMAIL.fullmatch(raw) is not None
    if len(raw) > 160 or len(re.findall(r"[A-Za-z\u0900-\u0D7F]", raw)) < 2:
        return False
    if entity_type == "PERSON":
        if re.fullmatch(r"[A-Za-z]+\s+Demo", raw, re.I):
            return False
        if any(character.isdigit() for character in raw) and re.fullmatch(r"[A-Za-z][A-Za-z .'-]+\sDemo\s\d{1,3}", raw, re.I) is None:
            return False
    return True
