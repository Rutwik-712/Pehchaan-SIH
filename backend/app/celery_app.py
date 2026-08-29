from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "threadline",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.tasks.pipeline", "app.tasks.reports"],
)
celery_app.conf.update(
    accept_content=["json"],
    task_serializer="json",
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 3600},
    result_expires=settings.celery_result_expires_seconds,
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=False,
    task_store_eager_result=False,
)
