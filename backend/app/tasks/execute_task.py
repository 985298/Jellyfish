"""统一 Celery 执行入口。

职责：
- Celery 统一只接收业务 task_id；
- 通过 GenerationTask.task_kind + registry 找到具体 WorkerTaskExecutor；
- 回写 executor_type / executor_task_id，便于排障。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta

from celery.result import AsyncResult

from app.core.celery_app import celery_app
from app.core.db_sync import sync_session_maker
from app.models.task import GenerationTask
from app.services.worker.task_registry import task_executor_registry

logger = logging.getLogger(__name__)


# ==================== Celery 探活缓存 (30s TTL) ====================
# 避免每个任务都阻塞 5s 等待 inspect.ping()
_CELERY_PROBE_TTL_SECONDS = 30.0
_celery_probe_lock = threading.Lock()
_celery_probe_result: tuple[bool, float] | None = None


def _is_celery_worker_alive() -> bool:
    """检查 Celery worker 是否在线，结果缓存 30s。

    原实现在每次派发前都同步 inspect.ping(timeout=5)：没有 worker 时每个任务
    白等 5 秒，批量提交 100 个任务光探活就要 500 秒，前端表现为"提交中卡住"。
    这里缓存探活结论，30s 内复用，避免把提交路径阻塞住。
    """
    global _celery_probe_result
    now = time.monotonic()
    cached = _celery_probe_result
    if cached is not None and (now - cached[1]) < _CELERY_PROBE_TTL_SECONDS:
        return cached[0]
    with _celery_probe_lock:
        cached = _celery_probe_result
        if cached is not None and (time.monotonic() - cached[1]) < _CELERY_PROBE_TTL_SECONDS:
            return cached[0]
        alive = False
        try:
            alive = bool(celery_app.control.inspect(timeout=5).ping())
        except Exception as exc:  # noqa: BLE001
            logger.warning("Celery worker probe failed: %s", exc)
            alive = False
        _celery_probe_result = (alive, time.monotonic())
        logger.info("Celery worker probe: alive=%s", alive)
        return alive


# ==================== 进程内回退执行器 ====================
def _resolve_in_process_concurrency() -> int:
    raw = os.environ.get("JELLYFISH_IN_PROCESS_CONCURRENCY")
    if raw is None or not str(raw).strip():
        return 4
    try:
        value = int(str(raw))
    except ValueError:
        logger.warning("JELLYFISH_IN_PROCESS_CONCURRENCY not an int: %r; falling back to 4", raw)
        return 4
    return value if value > 0 else 4


_IN_PROCESS_CONCURRENCY = _resolve_in_process_concurrency()
# 用信号量限流 + 每任务独立 daemon 线程，替代 ThreadPoolExecutor。
# ThreadPoolExecutor 在 max_workers=4 时会出现队列调度卡死（worker 空闲但不取
# 队列里下一个任务），导致 fan-out 阶段最后几个任务永远 pending。
_in_process_semaphore = threading.Semaphore(_IN_PROCESS_CONCURRENCY)
_in_process_lock = threading.Lock()
# 改用 dict 记录 task_id -> 入队时间戳，支持 TTL 清理。
_in_process_running: dict[str, float] = {}
_IN_PROCESS_DEDUP_TTL_SECONDS = 600.0


def _record_executor_dispatch(task_id: str, *, executor_type: str, executor_task_id: str | None) -> None:
    with sync_session_maker() as db:
        row = db.get(GenerationTask, task_id)
        if row is None:
            return
        row.executor_type = executor_type
        row.executor_task_id = executor_task_id
        db.commit()


def _mark_task_failed(task_id: str, reason: str) -> None:
    """将任务标记为 failed，防止孤儿 pending。"""
    with sync_session_maker() as db:
        row = db.get(GenerationTask, task_id)
        if row is None:
            return
        if row.status == "pending":
            row.status = "failed"
            row.error = reason[:500] if reason else "Unknown error"
            row.finished_at = datetime.utcnow()
            db.commit()
            logger.warning("Marked task %s as failed: %s", task_id, reason)


def enqueue_task_execution(task_id: str) -> AsyncResult:
    """分发任务执行：优先 Celery，失败则回退到进程内线程池。"""
    worker_alive = _is_celery_worker_alive()

    if not worker_alive:
        logger.warning("No Celery worker available for task %s — falling back to in-process execution", task_id)
        with _in_process_lock:
            now = time.monotonic()
            # TTL 清理：僵尸 task_id 清除后重新提交
            stale = [tid for tid, ts in _in_process_running.items() if now - ts > _IN_PROCESS_DEDUP_TTL_SECONDS]
            for tid in stale:
                _in_process_running.pop(tid, None)
                logger.warning("dedup TTL expired for task %s (was in running set >%ss), re-submitting", tid, _IN_PROCESS_DEDUP_TTL_SECONDS)
            if task_id in _in_process_running:
                logger.info("in-process task already running: task_id=%s (dedup)", task_id)
                _record_executor_dispatch(task_id, executor_type="in_process", executor_task_id=None)
                return AsyncResult(task_id, app=celery_app)
            _in_process_running[task_id] = now

        def _bg_run() -> None:
            try:
                run_task_celery(task_id)
            except Exception as e:
                logger.exception("in-process task execution failed: task_id=%s, error=%s", task_id, e)
                _mark_task_failed(task_id, f"In-process execution failed: {str(e)[:200]}")
            finally:
                with _in_process_lock:
                    _in_process_running.pop(task_id, None)

        # 每任务独立 daemon 线程 + 信号量限流，替代 ThreadPoolExecutor
        def _bg_run_with_semaphore() -> None:
            _in_process_semaphore.acquire()
            try:
                _bg_run()
            finally:
                _in_process_semaphore.release()

        try:
            t = threading.Thread(target=_bg_run_with_semaphore, name=f"jellyfish-task-{task_id[:8]}", daemon=True)
            t.start()
            _record_executor_dispatch(task_id, executor_type="in_process", executor_task_id=None)
            return AsyncResult(task_id, app=celery_app)
        except Exception as submit_err:
            logger.error("Failed to start in-process task %s: %s", task_id, submit_err)
            _mark_task_failed(task_id, f"Failed to start thread: {str(submit_err)}")
            return AsyncResult(task_id, app=celery_app)

    # Celery worker 在线，正常派发
    try:
        async_result = run_task_celery.delay(task_id)
        _record_executor_dispatch(task_id, executor_type="celery", executor_task_id=async_result.id)
        return async_result
    except Exception as exc:
        logger.error("Celery dispatch failed for task %s: %s", task_id, exc)
        _mark_task_failed(task_id, f"Celery dispatch failed: {str(exc)[:200]}")
        return AsyncResult(task_id, app=celery_app)


def revoke_task_execution(task_id: str, *, terminate: bool = True, signal: str = "SIGTERM") -> bool:
    with sync_session_maker() as db:
        row = db.get(GenerationTask, task_id)
        if row is None:
            return False
        if (row.executor_type or "").strip() != "celery":
            return False
        executor_task_id = (row.executor_task_id or "").strip()
        if not executor_task_id:
            return False

    try:
        AsyncResult(executor_task_id, app=celery_app).revoke(terminate=terminate, signal=signal)
    except Exception:  # noqa: BLE001
        logger.exception("failed to revoke celery task: task_id=%s executor_task_id=%s", task_id, executor_task_id)
        return False
    return True


# ==================== 启动时 Reaper：清理历史孤儿任务 ====================
def reaper_pending_tasks(threshold_minutes: int = 5) -> int:
    """
    清理超过 threshold_minutes 分钟仍处于 pending 或 running 状态的任务。
    这些任务很可能是进程重启后留下的孤儿。
    返回被清理的任务数量。
    """
    cleaned_count = 0
    cutoff = datetime.utcnow() - timedelta(minutes=threshold_minutes)
    
    with sync_session_maker() as db:
        orphan_rows = (
            db.query(GenerationTask)
            .filter(
                GenerationTask.status.in_(["pending", "running"]),
                GenerationTask.executor_type == "in_process",
                GenerationTask.created_at < cutoff,
            )
            .all()
        )
        
        for row in orphan_rows:
            old_status = row.status
            row.status = "failed"
            row.error = f"Cleaned: orphan task (was {old_status} for >{threshold_minutes}min)"
            row.finished_at = datetime.utcnow()
            cleaned_count += 1
            logger.warning("Reaped orphan task %s: was %s, created at %s", row.id, old_status, row.created_at)
        
        if cleaned_count > 0:
            db.commit()
            logger.info("Reaper completed: cleaned %d orphan tasks", cleaned_count)
    
    return cleaned_count


@celery_app.task(name="task.execute")
def run_task_celery(task_id: str) -> None:
    with sync_session_maker() as db:
        row = db.get(GenerationTask, task_id)
        if row is None:
            return
        task_kind = (row.task_kind or "").strip() or str((row.payload or {}).get("task_kind") or "").strip()
    executor = task_executor_registry.resolve(task_kind)
    executor.run(task_id)
