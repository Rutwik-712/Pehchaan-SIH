import os


# Celery executes in-process during tests; Redis remains required in the live Phase 4 proof.
os.environ.setdefault("CELERY_TASK_ALWAYS_EAGER", "true")
os.environ["DATABASE_URL"] = f"sqlite:////private/tmp/sih-phase4-tests-{os.getpid()}.db"
os.environ["LOCAL_OBJECT_ROOT"] = f"/private/tmp/sih-phase4-objects-{os.getpid()}"
