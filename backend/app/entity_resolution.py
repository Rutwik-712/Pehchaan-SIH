from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Sequence, Tuple
from uuid import NAMESPACE_URL, uuid5

import pandas as pd
import splink.comparison_library as comparison_library
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from splink import DuckDBAPI, Linker, SettingsCreator

from app.config import get_settings
from app.models import (
    ExtractedMention,
    ResolutionCandidate,
    ResolutionRun,
    ResolvedEntity,
    ResolvedMention,
)

TRUSTED_REVIEW_STATUSES = {"confirmed", "corrected"}
FUZZY_ENTITY_TYPES = {"PERSON", "ORGANIZATION", "LOCATION"}
RESOLUTION_VERSION = "splink-duckdb-phase6-v1"


class UnionFind:
    def __init__(self, values: Iterable[str]):
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[max(left_root, right_root)] = min(left_root, right_root)


def _ordered_pair(left_id: str, right_id: str) -> Tuple[str, str]:
    return (left_id, right_id) if left_id < right_id else (right_id, left_id)


def _splink_predictions(mentions: Sequence[ExtractedMention]) -> List[Tuple[str, str, float]]:
    fuzzy_mentions = [item for item in mentions if item.entity_type in FUZZY_ENTITY_TYPES]
    if len(fuzzy_mentions) < 2:
        return []
    records = [
        {
            "unique_id": item.id,
            "entity_type": item.entity_type,
            "normalized_value": item.normalized_value,
        }
        for item in fuzzy_mentions
    ]
    name_comparison = comparison_library.JaroWinklerAtThresholds(
        "normalized_value", [0.95, 0.88]
    ).configure(
        m_probabilities=[0.70, 0.20, 0.08, 0.02],
        u_probabilities=[0.001, 0.004, 0.045, 0.95],
    )
    settings = SettingsCreator(
        link_type="dedupe_only",
        probability_two_random_records_match=0.10,
        blocking_rules_to_generate_predictions=["l.entity_type = r.entity_type"],
        comparisons=[name_comparison],
        additional_columns_to_retain=["entity_type"],
    )
    linker = Linker(
        pd.DataFrame(records),
        settings,
        DuckDBAPI(),
        set_up_basic_logging=False,
    )
    frame = linker.inference.predict(
        threshold_match_probability=get_settings().resolution_candidate_threshold
    ).as_pandas_dataframe()
    output: List[Tuple[str, str, float]] = []
    for row in frame.to_dict(orient="records"):
        left_id, right_id = _ordered_pair(str(row["unique_id_l"]), str(row["unique_id_r"]))
        output.append((left_id, right_id, round(float(row["match_probability"]), 6)))
    return output


def _canonical_mention(cluster: Sequence[ExtractedMention]) -> ExtractedMention:
    counts = Counter(item.normalized_value for item in cluster)
    return sorted(
        cluster,
        key=lambda item: (
            -counts[item.normalized_value],
            -len(item.value),
            item.value.casefold(),
            item.id,
        ),
    )[0]


def run_entity_resolution(session: Session, case_id: str, requested_by_id: str) -> ResolutionRun:
    settings = get_settings()
    run = ResolutionRun(
        case_id=case_id,
        requested_by_id=requested_by_id,
        status="running",
        settings_snapshot={
            "version": RESOLUTION_VERSION,
            "trusted_statuses": sorted(TRUSTED_REVIEW_STATUSES),
            "candidate_threshold": settings.resolution_candidate_threshold,
            "fuzzy_entity_types": sorted(FUZZY_ENTITY_TYPES),
            "automatic_fuzzy_merge": False,
        },
    )
    session.add(run)
    session.flush()
    try:
        mentions = list(
            session.scalars(
                select(ExtractedMention)
                .where(
                    ExtractedMention.case_id == case_id,
                    ExtractedMention.status.in_(TRUSTED_REVIEW_STATUSES),
                )
                .order_by(ExtractedMention.created_at.asc(), ExtractedMention.id.asc())
            ).all()
        )
        if len(mentions) > settings.graph_max_nodes_per_case:
            raise ValueError("Reviewed mention count exceeds GRAPH_MAX_NODES_PER_CASE")
        run.mention_count = len(mentions)
        mention_by_id = {item.id: item for item in mentions}
        union_find = UnionFind(mention_by_id)

        exact_groups: Dict[Tuple[str, str], List[str]] = defaultdict(list)
        for mention in mentions:
            exact_groups[(mention.entity_type, mention.normalized_value)].append(mention.id)
        for member_ids in exact_groups.values():
            for member_id in member_ids[1:]:
                union_find.union(member_ids[0], member_id)

        existing_candidates = {
            _ordered_pair(item.left_mention_id, item.right_mention_id): item
            for item in session.scalars(
                select(ResolutionCandidate).where(ResolutionCandidate.case_id == case_id)
            ).all()
        }
        predictions = _splink_predictions(mentions)
        for left_id, right_id, probability in predictions:
            left = mention_by_id[left_id]
            right = mention_by_id[right_id]
            if left.normalized_value == right.normalized_value:
                continue
            pair = (left_id, right_id)
            candidate = existing_candidates.get(pair)
            if candidate is None:
                candidate = ResolutionCandidate(
                    case_id=case_id,
                    left_mention_id=left_id,
                    right_mention_id=right_id,
                    entity_type=left.entity_type,
                    match_probability=probability,
                    method=RESOLUTION_VERSION,
                )
                session.add(candidate)
                existing_candidates[pair] = candidate
            else:
                candidate.match_probability = probability
                candidate.updated_at = datetime.now(timezone.utc)
            if candidate.status == "confirmed":
                union_find.union(left_id, right_id)

        session.execute(
            delete(ResolvedMention).where(ResolvedMention.case_id == case_id)
        )
        session.execute(
            delete(ResolvedEntity).where(ResolvedEntity.case_id == case_id)
        )
        session.flush()

        clusters: Dict[str, List[ExtractedMention]] = defaultdict(list)
        for mention in mentions:
            clusters[union_find.find(mention.id)].append(mention)

        for cluster in clusters.values():
            canonical = _canonical_mention(cluster)
            normalized_values = sorted({item.normalized_value for item in cluster})
            entity_id = str(
                uuid5(
                    NAMESPACE_URL,
                    f"threadline:{case_id}:{canonical.entity_type}:{'|'.join(normalized_values)}",
                )
            )
            fuzzy_probabilities = [
                candidate.match_probability
                for pair, candidate in existing_candidates.items()
                if candidate.status == "confirmed"
                and pair[0] in {item.id for item in cluster}
                and pair[1] in {item.id for item in cluster}
            ]
            method = "splink_confirmed" if len(normalized_values) > 1 else "exact_normalized_value"
            confidence = min(fuzzy_probabilities) if fuzzy_probabilities else 1.0
            session.add(
                ResolvedEntity(
                    id=entity_id,
                    case_id=case_id,
                    entity_type=canonical.entity_type,
                    canonical_value=canonical.value,
                    normalized_value=canonical.normalized_value,
                    mention_count=len(cluster),
                    resolution_method=method,
                    confidence=confidence,
                )
            )
            session.flush()
            for mention in cluster:
                session.add(
                    ResolvedMention(
                        mention_id=mention.id,
                        entity_id=entity_id,
                        run_id=run.id,
                        case_id=case_id,
                        match_probability=confidence if method == "splink_confirmed" else 1.0,
                        resolution_method=method,
                    )
                )

        run.entity_count = len(clusters)
        run.candidate_count = sum(
            1 for item in existing_candidates.values() if item.status == "pending_review"
        )
        run.status = "completed"
        run.completed_at = datetime.now(timezone.utc)
        session.flush()
        return run
    except Exception as exc:
        run.status = "failed"
        run.error_message = f"{type(exc).__name__}: {str(exc)[:420]}"
        run.completed_at = datetime.now(timezone.utc)
        session.flush()
        raise
