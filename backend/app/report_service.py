from __future__ import annotations

import hashlib
import re
import tempfile
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Case,
    CaseReport,
    EvidenceSource,
    ExtractedMention,
    ExtractedRelation,
    GraphAlert,
    ResolvedEntity,
)
from app.storage import get_object_storage

TRUSTED_REVIEW_STATUSES = {"confirmed", "corrected"}


def build_report_content(session: Session, report: CaseReport) -> Dict[str, Any]:
    case = session.get(Case, report.case_id)
    if case is None:
        raise ValueError("Case not found")
    sources = list(
        session.scalars(
            select(EvidenceSource)
            .where(EvidenceSource.case_id == report.case_id)
            .order_by(EvidenceSource.created_at.asc())
        ).all()
    )
    entities = list(
        session.scalars(
            select(ResolvedEntity)
            .where(ResolvedEntity.case_id == report.case_id)
            .order_by(ResolvedEntity.priority_score.desc(), ResolvedEntity.canonical_value.asc())
            .limit(50)
        ).all()
    )
    mentions = list(
        session.scalars(
            select(ExtractedMention)
            .where(
                ExtractedMention.case_id == report.case_id,
                ExtractedMention.status.in_(TRUSTED_REVIEW_STATUSES),
            )
            .order_by(ExtractedMention.created_at.asc())
        ).all()
    )
    mention_map = {item.id: item for item in mentions}
    relations = list(
        session.scalars(
            select(ExtractedRelation)
            .where(
                ExtractedRelation.case_id == report.case_id,
                ExtractedRelation.status.in_(TRUSTED_REVIEW_STATUSES),
            )
            .order_by(ExtractedRelation.created_at.asc())
            .limit(100)
        ).all()
    )
    source_map = {item.id: item for item in sources}
    citations: List[Dict[str, Any]] = []
    reviewed_relationships: List[Dict[str, Any]] = []
    for relation in relations:
        left = mention_map.get(relation.subject_mention_id)
        right = mention_map.get(relation.object_mention_id)
        if left is None or right is None:
            continue
        citation_number = len(citations) + 1
        citations.append(
            {
                "number": citation_number,
                "evidence_id": relation.evidence_id,
                "source": source_map.get(relation.evidence_id).original_filename if source_map.get(relation.evidence_id) else "Reviewed evidence",
                "page": left.page_number,
                "excerpt": relation.source_excerpt,
            }
        )
        reviewed_relationships.append(
            {
                "subject": left.value,
                "relation": relation.relation_type,
                "object": right.value,
                "citation": citation_number,
            }
        )
    pending_count = int(
        (session.scalar(select(func.count()).select_from(ExtractedMention).where(
            ExtractedMention.case_id == report.case_id,
            ExtractedMention.status == "pending_review",
        )) or 0)
        + (session.scalar(select(func.count()).select_from(ExtractedRelation).where(
            ExtractedRelation.case_id == report.case_id,
            ExtractedRelation.status == "pending_review",
        )) or 0)
    )
    open_alerts = int(
        session.scalar(select(func.count()).select_from(GraphAlert).where(
            GraphAlert.case_id == report.case_id,
            GraphAlert.status != "reviewed",
        )) or 0
    )
    limitations = [
        "Only confirmed or corrected extraction records are presented as reviewed facts.",
        f"{pending_count} extraction items remain pending human review and are excluded from confirmed findings.",
        "Graph prominence and co-occurrence describe evidence structure; they do not establish guilt, intent, or identity.",
        "Machine-assisted extraction and summarization require investigator verification against cited originals.",
    ]
    return {
        "case": {
            "id": case.id,
            "title": case.title,
            "jurisdiction": case.jurisdiction,
            "classification": case.classification,
            "scope": report.scope_note,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": [
            {"id": item.id, "filename": item.original_filename, "sha256": item.sha256, "created_at": item.created_at.isoformat()}
            for item in sources
        ],
        "entities": [
            {
                "id": item.id,
                "type": item.entity_type,
                "label": item.canonical_value,
                "mention_count": item.mention_count,
                "degree": item.degree,
                "priority_score": round(item.priority_score, 4),
            }
            for item in entities
        ],
        "relationships": reviewed_relationships,
        "citations": citations,
        "metrics": {
            "source_count": len(sources),
            "reviewed_entity_count": len(entities),
            "reviewed_relationship_count": len(reviewed_relationships),
            "pending_review_count": pending_count,
            "open_alert_count": open_alerts,
        },
        "limitations": limitations,
        "interpretation_boundary": "This report is analytical assistance and does not determine guilt or recommend enforcement action.",
    }


def _pdf_safe(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text.encode("latin-1", "replace").decode("latin-1")


def render_report_pdf(report: CaseReport, content: Dict[str, Any], output_path: Path) -> None:
    import fitz

    document = fitz.open()
    page = document.new_page(width=595, height=842)
    y = 48.0

    def line(value: Any, *, size: float = 9, bold: bool = False, gap: float = 4) -> None:
        nonlocal page, y
        wrapped = textwrap.wrap(_pdf_safe(value), width=96) or [""]
        for part in wrapped:
            if y > 790:
                page = document.new_page(width=595, height=842)
                y = 48
                page.insert_text((42, 28), f"{report.classification} | Case brief v{report.version}", fontsize=7, color=(0.35, 0.35, 0.35))
            page.insert_text((42, y), part, fontsize=size, fontname="hebo" if bold else "helv", color=(0.08, 0.08, 0.08))
            y += size + 3
        y += gap

    page.draw_rect(fitz.Rect(0, 0, 595, 30), color=(0.85, 0.68, 0.08), fill=(0.96, 0.78, 0.12))
    page.insert_text((42, 20), f"{report.classification} | IMMUTABLE CASE BRIEF | VERSION {report.version}", fontsize=8, fontname="hebo")
    line(report.title, size=18, bold=True, gap=8)
    line(f"Case {report.case_id} | Generated {content['generated_at']}", size=8)
    line(f"Scope: {report.scope_note or 'All currently reviewed case evidence'}", size=9, gap=12)
    line("EVIDENCE SNAPSHOT", size=11, bold=True)
    metrics = content["metrics"]
    line(f"Sources: {metrics['source_count']} | Reviewed entities: {metrics['reviewed_entity_count']} | Reviewed relationships: {metrics['reviewed_relationship_count']} | Pending review: {metrics['pending_review_count']}")
    line("SOURCES USED", size=11, bold=True)
    for source in content["sources"]:
        line(f"- {source['filename']} | SHA-256 {source['sha256']}", size=8)
    line("CONFIRMED ENTITIES", size=11, bold=True)
    if not content["entities"]:
        line("No resolved reviewed entities were available at generation time.")
    for entity in content["entities"]:
        line(f"- {entity['type']}: {entity['label']} | mentions {entity['mention_count']} | structural degree {entity['degree']}", size=8)
    line("CONFIRMED RELATIONSHIPS", size=11, bold=True)
    if not content["relationships"]:
        line("No reviewed relationships were available at generation time.")
    for item in content["relationships"]:
        line(f"- {item['subject']} -- {item['relation']} --> {item['object']} [{item['citation']}]", size=8)
    line("CITATIONS", size=11, bold=True)
    for item in content["citations"]:
        line(f"[{item['number']}] {item['source']}, page {item['page']}: {item['excerpt']}", size=8)
    line("LIMITATIONS", size=11, bold=True)
    for limitation in content["limitations"]:
        line(f"- {limitation}", size=8)
    line(content["interpretation_boundary"], size=9, bold=True)
    document.set_metadata({"title": report.title, "subject": "Source-backed case brief", "keywords": "restricted, reviewed evidence, no guilt determination"})
    document.save(str(output_path), deflate=True)
    document.close()


def generate_and_store_report(session: Session, report: CaseReport) -> CaseReport:
    content = build_report_content(session, report)
    report.status = "generating"
    session.commit()
    object_key = f"cases/{report.case_id}/reports/{report.id}/case-brief-v{report.version}.pdf"
    with tempfile.TemporaryDirectory(prefix="threadline-report-") as temp_dir:
        output_path = Path(temp_dir) / "case-brief.pdf"
        render_report_pdf(report, content, output_path)
        payload_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()
        stored = get_object_storage().put_file(
            object_key,
            output_path,
            "application/pdf",
            {"sha256": payload_hash, "case-id": report.case_id, "report-id": report.id},
        )
        del stored
        report.content = content
        report.limitations = content["limitations"]
        report.citation_count = len(content["citations"])
        report.object_key = object_key
        report.sha256 = payload_hash
        report.size_bytes = output_path.stat().st_size
    report.status = "completed"
    report.completed_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(report)
    return report
