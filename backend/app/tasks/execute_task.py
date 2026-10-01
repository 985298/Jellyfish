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
from concurrent.futures import ThreadPoolExecutor

from celery.result import AsyncResult

from app.core.celery_app import celery_app
from app.core.db_sync import sync_session_maker
from app.models.task import GenerationTask
from app.services.worker.task_registry import task_executor_registry

logger = logging.getLogger(__name__)


# 进程内回退执行器：当 Celery worker 不在线时，任务在这里跑。
# 原实现为每次请求新建一个 daemon 线程，无任何上限——视频生成并发发起时
# 会同时拉起 N 条线程，每条都向供应商发起长轮询 + 大文件下载，
# 把事件循环 / 出站连接 / 内存打爆。这里用有界线程池做并发控制。
# 上限可通过环境变量 JELLYFISH_IN_PROCESS_CONCURRENCY 覆盖，默认 4。
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
_in_process_executor = ThreadPoolExecutor(
    max_workers=_IN_PROCESS_CONCURRENCY,
    thread_name_prefix="jellyfish-task",
)
_in_process_lock = threading.Lock()
_in_process_running: set[str] = set()


def _record_executor_dispatch(task_id: str, *, executor_type: str, executor_task_id: str | None) -> None:
    with sync_session_maker() as db:
        row = db.get(GenerationTask, task_id)
        if row is None:
            return
        row.executor_type = executor_type
        row.executor_task_id = executor_task_id
        db.commit()


def enqueue_task_execution(task_id: str) -> AsyncResult:
    # 检测 Celery worker 是否在线；不在线则回退到进程内有界线程池执行
    try:
        inspect = celery_app.control.inspect(timeout=1)
        ping_result = inspect.ping()
        if not ping_result:
            raise RuntimeError("No Celery worker responding")
        async_result = run_task_celery.delay(task_id)
    except Exception as exc:
        logger.warning("Celery dispatch failed for task %s: %s — falling back to in-process execution", task_id, exc)
        # 同一 task_id 重复提交时去重，避免线程池里堆积同一任务的多个副本
        # （前端重试 / 双击 / SSE 重连都会触发）。
        with _in_process_lock:
            if task_id in _in_process_running:
                logger.info("in-process task already running: task_id=%s (dedup)", task_id)
                _record_executor_dispatch(task_id, executor_type="in_process", executor_task_id=None)
                return AsyncResult(task_id, app=celery_app)
            _in_process_running.add(task_id)

        def _bg_run() -> None:
            try:
                run_task_celery(task_id)
            except Exception:
                logger.exception("in-process task execution failed: task_id=%s", task_id)
            finally:
                with _in_process_lock:
                    _in_process_running.discard(task_id)

        _in_process_executor.submit(_bg_run)
        _record_executor_dispatch(task_id, executor_type="in_process", executor_task_id=None)
        return AsyncResult(task_id, app=celery_app)

    _record_executor_dispatch(
        task_id,
        executor_type="celery",
        executor_task_id=async_result.id,
    )
    return async_result


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


@celery_app.task(name="task.execute")
def run_task_celery(task_id: str) -> None:
    with sync_session_maker() as db:
        row = db.get(GenerationTask, task_id)
        if row is None:
            return
        task_kind = (row.task_kind or "").strip() or str((row.payload or {}).get("task_kind") or "").strip()
    executor = task_executor_registry.resolve(task_kind)
    executor.run(task_id)
