from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Tuple
from urllib.parse import urlparse


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_env: str
    app_debug: bool
    api_v1_prefix: str
    frontend_origin: str
    build_version: str
    database_url: str
    jwt_secret: str
    access_token_minutes: int
    refresh_token_days: int
    demo_account_password: str
    seed_demo_data: bool
    object_storage_backend: str
    local_object_root: str
    max_upload_bytes: int
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str
    minio_secure: bool
    seed_mobile_fraud_demo: bool = False
    celery_broker_url: str = "redis://127.0.0.1:6379/0"
    celery_result_backend: str = "redis://127.0.0.1:6379/1"
    celery_task_always_eager: bool = False
    celery_result_expires_seconds: int = 3600
    spacy_model: str = "en_core_web_sm"
    extraction_review_threshold: int = 70
    paddleocr_enabled: bool = False
    paddleocr_language: str = "en"
    paddleocr_version: str = "PP-OCRv3"
    qwen_enabled: bool = False
    qwen_base_url: str = "http://127.0.0.1:11434"
    qwen_model: str = "qwen2.5:7b-instruct-q4_K_M"
    qwen_timeout_seconds: int = 180
    qwen_num_ctx: int = 4096
    qwen_allowed_hosts: Tuple[str, ...] = ("127.0.0.1", "localhost", "host.docker.internal", "ollama")
    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "SIH1@2026"
    neo4j_database: str = "neo4j"
    neo4j_allowed_hosts: Tuple[str, ...] = ("127.0.0.1", "localhost", "neo4j")
    resolution_candidate_threshold: float = 0.60
    graph_max_nodes_per_case: int = 5000

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            app_name=os.getenv("APP_NAME", "Criminal Network Analysis System"),
            app_env=os.getenv("APP_ENV", "development"),
            app_debug=_as_bool(os.getenv("APP_DEBUG"), default=True),
            api_v1_prefix=os.getenv("API_V1_PREFIX", "/api/v1"),
            frontend_origin=os.getenv("FRONTEND_ORIGIN", "http://localhost:5173"),
            build_version=os.getenv("BUILD_VERSION", "0.8.0-phase8"),
            database_url=os.getenv("DATABASE_URL", "sqlite:///./data/sih.db"),
            jwt_secret=os.getenv(
                "JWT_SECRET",
                "phase2-local-only-change-before-shared-deployment-2026",
            ),
            access_token_minutes=int(os.getenv("ACCESS_TOKEN_MINUTES", "30")),
            refresh_token_days=int(os.getenv("REFRESH_TOKEN_DAYS", "7")),
            demo_account_password=os.getenv("DEMO_ACCOUNT_PASSWORD", "SIH1@2026"),
            seed_demo_data=_as_bool(os.getenv("SEED_DEMO_DATA"), default=True),
            seed_mobile_fraud_demo=_as_bool(os.getenv("SEED_MOBILE_FRAUD_DEMO"), default=False),
            object_storage_backend=os.getenv("OBJECT_STORAGE_BACKEND", "local").lower(),
            local_object_root=os.getenv("LOCAL_OBJECT_ROOT", "./data/objects"),
            max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024))),
            minio_endpoint=os.getenv("MINIO_ENDPOINT", "127.0.0.1:9000"),
            minio_access_key=os.getenv("MINIO_ACCESS_KEY", "sih_minio"),
            minio_secret_key=os.getenv("MINIO_SECRET_KEY", "replace-me"),
            minio_bucket=os.getenv("MINIO_BUCKET", "evidence"),
            minio_secure=_as_bool(os.getenv("MINIO_SECURE"), default=False),
            celery_broker_url=os.getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0"),
            celery_result_backend=os.getenv("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/1"),
            celery_task_always_eager=_as_bool(os.getenv("CELERY_TASK_ALWAYS_EAGER"), default=False),
            celery_result_expires_seconds=int(os.getenv("CELERY_RESULT_EXPIRES_SECONDS", "3600")),
            spacy_model=os.getenv("SPACY_MODEL", "en_core_web_sm"),
            extraction_review_threshold=int(os.getenv("EXTRACTION_REVIEW_THRESHOLD", "70")),
            paddleocr_enabled=_as_bool(os.getenv("PADDLEOCR_ENABLED"), default=False),
            paddleocr_language=os.getenv("PADDLEOCR_LANGUAGE", "en"),
            paddleocr_version=os.getenv("PADDLEOCR_VERSION", "PP-OCRv3"),
            qwen_enabled=_as_bool(os.getenv("QWEN_ENABLED"), default=False),
            qwen_base_url=os.getenv("QWEN_BASE_URL", "http://127.0.0.1:11434").rstrip("/"),
            qwen_model=os.getenv("QWEN_MODEL", "qwen2.5:7b-instruct-q4_K_M"),
            qwen_timeout_seconds=int(os.getenv("QWEN_TIMEOUT_SECONDS", "180")),
            qwen_num_ctx=int(os.getenv("QWEN_NUM_CTX", "4096")),
            qwen_allowed_hosts=tuple(
                item.strip().lower()
                for item in os.getenv(
                    "QWEN_ALLOWED_HOSTS",
                    "127.0.0.1,localhost,host.docker.internal,ollama",
                ).split(",")
                if item.strip()
            ),
            neo4j_uri=os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"),
            neo4j_user=os.getenv("NEO4J_USER", "neo4j"),
            neo4j_password=os.getenv("NEO4J_PASSWORD", "SIH1@2026"),
            neo4j_database=os.getenv("NEO4J_DATABASE", "neo4j"),
            neo4j_allowed_hosts=tuple(
                item.strip().lower()
                for item in os.getenv("NEO4J_ALLOWED_HOSTS", "127.0.0.1,localhost,neo4j").split(",")
                if item.strip()
            ),
            resolution_candidate_threshold=float(os.getenv("RESOLUTION_CANDIDATE_THRESHOLD", "0.60")),
            graph_max_nodes_per_case=int(os.getenv("GRAPH_MAX_NODES_PER_CASE", "5000")),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings.from_environment()


def validate_security_settings(settings: Settings) -> None:
    if len(settings.jwt_secret) < 32:
        raise RuntimeError("JWT_SECRET must contain at least 32 characters")
    if settings.app_env.lower() == "production" and settings.jwt_secret.startswith("phase2-local-only"):
        raise RuntimeError("Production requires a non-default JWT_SECRET")
    if settings.app_env.lower() == "production" and settings.seed_demo_data:
        raise RuntimeError("Production must disable SEED_DEMO_DATA")
    if settings.object_storage_backend not in {"local", "minio"}:
        raise RuntimeError("OBJECT_STORAGE_BACKEND must be 'local' or 'minio'")
    if not 0 <= settings.extraction_review_threshold <= 100:
        raise RuntimeError("EXTRACTION_REVIEW_THRESHOLD must be between 0 and 100")
    if settings.qwen_enabled:
        parsed = urlparse(settings.qwen_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise RuntimeError("QWEN_BASE_URL must be an HTTP(S) URL")
        if parsed.hostname.lower() not in settings.qwen_allowed_hosts:
            raise RuntimeError("QWEN_BASE_URL host is not in QWEN_ALLOWED_HOSTS")
    if settings.qwen_num_ctx < 512:
        raise RuntimeError("QWEN_NUM_CTX must be at least 512")
    parsed_neo4j = urlparse(settings.neo4j_uri)
    if parsed_neo4j.scheme not in {"bolt", "bolt+s", "bolt+ssc", "neo4j", "neo4j+s", "neo4j+ssc"}:
        raise RuntimeError("NEO4J_URI must use a supported Neo4j driver scheme")
    if not parsed_neo4j.hostname or parsed_neo4j.hostname.lower() not in settings.neo4j_allowed_hosts:
        raise RuntimeError("NEO4J_URI host is not in NEO4J_ALLOWED_HOSTS")
    if not 0 <= settings.resolution_candidate_threshold <= 1:
        raise RuntimeError("RESOLUTION_CANDIDATE_THRESHOLD must be between 0 and 1")
    if settings.graph_max_nodes_per_case < 1:
        raise RuntimeError("GRAPH_MAX_NODES_PER_CASE must be positive")
