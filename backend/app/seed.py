from __future__ import annotations

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import Case, CaseAssignment, Role, User
from app.security import hash_password

DEMO_USERS = (
    {"username": "constable.demo", "full_name": "Constable C. Kumar", "email": "constable.demo@sih.local", "role": Role.CONSTABLE.value},
    {"username": "investigator.demo", "full_name": "Inspector A. Rao", "email": "investigator.demo@sih.local", "role": Role.INVESTIGATOR.value},
    {"username": "sp.demo", "full_name": "SP N. Iyer", "email": "sp.demo@sih.local", "role": Role.SP.value},
)

CORE_DEMO_CASES = (
    {"id": "KSP-CR-2048", "title": "Majestic Corridor Link Analysis", "jurisdiction": "Bengaluru Central", "classification": "RESTRICTED", "description": "Synthetic demonstration case for source-backed network analysis."},
    {"id": "KSP-CR-2099", "title": "Harbour Ledger Review", "jurisdiction": "Mangaluru City", "classification": "RESTRICTED", "description": "Unassigned synthetic case used to verify case isolation."},
)
MOBILE_FRAUD_DEMO_CASE = {
    "id": "KSP-MF-2101",
    "title": "Mobile Wallet Fraud Network",
    "jurisdiction": "Bengaluru Cyber Crime",
    "classification": "RESTRICTED",
    "description": "Fictional mobile-fraud demonstration case containing five synthetic people and reviewed, source-backed relationships.",
}
DEMO_CASES = CORE_DEMO_CASES + tuple(
    {
        "id": f"KSP-SYN-{index:03d}",
        "title": f"Synthetic Network Review {index:02d}",
        "jurisdiction": ("Bengaluru Central", "Mysuru City", "Belagavi", "Hubballi-Dharwad")[index % 4],
        "classification": "RESTRICTED",
        "description": "Fictional demonstration case. All people, identifiers, places and events are synthetic and do not describe real allegations.",
    }
    for index in range(3, 21)
)


def seed_phase2_data() -> None:
    settings = get_settings()
    cases_to_seed = DEMO_CASES + ((MOBILE_FRAUD_DEMO_CASE,) if settings.seed_mobile_fraud_demo else ())
    with SessionLocal() as session:
        for user_data in DEMO_USERS:
            existing = session.scalar(select(User).where(User.username == user_data["username"]))
            if existing is None:
                session.add(User(password_hash=hash_password(settings.demo_account_password), **user_data))
        for case_data in cases_to_seed:
            if session.get(Case, case_data["id"]) is None:
                session.add(Case(**case_data))
        session.commit()

        # Keep KSP-CR-2099 unassigned for negative case-isolation checks. All
        # other fictional cases are visible to the two scoped demo roles.
        for case_data in cases_to_seed:
            if case_data["id"] == "KSP-CR-2099":
                continue
            for username in ("constable.demo", "investigator.demo"):
                user = session.scalar(select(User).where(User.username == username))
                assignment = session.scalar(
                    select(CaseAssignment).where(
                        CaseAssignment.case_id == case_data["id"],
                        CaseAssignment.user_id == user.id,
                    )
                )
                if assignment is None:
                    session.add(CaseAssignment(case_id=case_data["id"], user_id=user.id))
        session.commit()
