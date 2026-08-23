from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app import main
from app.main import (
    enqueue_ai_task,
    enqueue_organize_component_tasks,
    health_status,
    recover_stuck_ai_tasks,
    resolve_superseded_ai_failures,
)
from app.models import AiTask, Category, Component


def make_db(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'ai-health.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return engine, Session()


def test_organize_queue_limit_counts_actionable_rows_not_first_catalog_rows(tmp_path):
    engine, db = make_db(tmp_path)
    category = Category(name="电阻", color="#eeeeee")
    db.add(category)
    db.flush()
    db.add_all(
        [
            Component(id=index, name=f"已整理电阻 {index}", category_id=category.id, tags="贴片", quantity=1)
            for index in range(1, 86)
        ]
        + [
            Component(id=index, name=f"待整理元器件 {index}", category_id=None, tags="待整理", quantity=1)
            for index in range(86, 91)
        ]
    )
    db.commit()

    assert enqueue_organize_component_tasks(db, limit=2) == 2
    db.commit()
    queued_targets = [
        row.target_id
        for row in db.query(AiTask).filter(AiTask.task_type == "component_organize").order_by(AiTask.id).all()
    ]
    assert queued_targets == [86, 87]

    db.close()
    engine.dispose()


def test_historical_failure_is_superseded_only_when_no_longer_actionable(tmp_path):
    engine, db = make_db(tmp_path)
    category = Category(name="电容", color="#eeeeee")
    db.add(category)
    db.flush()
    valid = Component(id=1, name="100nF 50V 0603 MLCC", category_id=category.id, tags="贴片", quantity=1)
    unresolved = Component(id=2, name="待分类长名称元器件", category_id=None, tags="待整理", quantity=1)
    db.add_all([valid, unresolved])
    db.flush()
    db.add_all(
        [
            AiTask(task_type="component_organize", target_type="component", target_id=1, status="failed", input_hash="old"),
            AiTask(task_type="component_organize", target_type="component", target_id=2, status="failed", input_hash="old"),
        ]
    )
    db.commit()

    assert resolve_superseded_ai_failures(db) == 1
    db.commit()
    assert db.query(AiTask).filter(AiTask.target_id == 1).one().status == "superseded"
    assert db.query(AiTask).filter(AiTask.target_id == 2).one().status == "failed"

    db.close()
    engine.dispose()


def test_orphaned_processing_task_is_requeued_without_counting_provider_retry(tmp_path, monkeypatch):
    engine, db = make_db(tmp_path)
    component = Component(id=1, name="待恢复任务", quantity=1, ai_status="processing", ai_error="旧错误")
    task = AiTask(
        task_type="component_analyze",
        target_type="component",
        target_id=1,
        status="processing",
        retry_count=2,
        started_at=datetime(2026, 8, 15, 8, 0, 0),
    )
    db.add_all([component, task])
    db.commit()
    monkeypatch.setattr(main, "AI_TASK_STUCK_SECONDS", 600)

    recovered = recover_stuck_ai_tasks(db, datetime(2026, 8, 15, 8, 20, 0))
    db.commit()
    assert recovered == 1
    assert task.status == "pending"
    assert task.retry_count == 2
    assert task.next_attempt_at == datetime(2026, 8, 15, 8, 20, 0)
    assert component.ai_status == "pending"
    assert component.ai_error is None

    db.close()
    engine.dispose()


def test_retry_creates_new_task_and_preserves_failed_audit_record(tmp_path):
    engine, db = make_db(tmp_path)
    failed = AiTask(
        task_type="component_organize",
        target_type="component",
        target_id=9,
        status="failed",
        retry_count=8,
        input_hash="old-hash",
        error_message="provider rejected the request",
    )
    db.add(failed)
    db.commit()

    retry = enqueue_ai_task(db, "component_organize", "component", 9, "new-hash")
    db.commit()

    assert retry.id != failed.id
    assert retry.status == "pending"
    assert retry.retry_count == 0
    assert retry.input_hash == "new-hash"
    assert failed.status == "failed"
    assert failed.retry_count == 8
    assert failed.error_message == "provider rejected the request"

    db.close()
    engine.dispose()


def test_health_reports_worker_provider_queue_and_stuck_dimensions(tmp_path, monkeypatch):
    engine, db = make_db(tmp_path)
    db.add(
        AiTask(
            task_type="component_analyze",
            target_type="component",
            target_id=1,
            status="completed",
            finished_at=datetime.now() - timedelta(minutes=1),
        )
    )
    db.commit()
    monkeypatch.setenv("AI_API_KEY", "configured-for-test")
    monkeypatch.setenv("AI_BASE_URL", "https://ai.example.test/v1")
    monkeypatch.setattr(main, "AI_WORKER_RUNNING", True)
    monkeypatch.setattr(
        main,
        "account_center_public_health_component",
        lambda: main.public_status_component("auth", "operational", "统一账号可响应"),
    )

    result = health_status(db)
    ai = next(row for row in result["components"] if row["name"] == "ai")
    assert result["ok"] is True
    assert ai["status"] == "operational"
    assert result["metrics"]["aiWorkerRunning"] is True
    assert result["metrics"]["aiProviderConfigured"] is True
    assert result["metrics"]["failedJobs"] == 0
    assert result["metrics"]["stuckJobs"] == 0

    db.close()
    engine.dispose()
