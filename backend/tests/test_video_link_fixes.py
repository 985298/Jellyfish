"""视频生成链路修复后的 smoke test。

覆盖三处关键修复：
1. RustFS 上传：ACL 不被支持时自动去 ACL 重试（不依赖真实 S3）。
2. 进程内回退执行器：同一 task_id 重复提交只跑一次（并发去重）。
3. OpenAI 视频 adapter：5xx 重试，最终成功。
4. 轮询软截止：超过 deadline 抛 RuntimeError，错误能写进 task.error。
"""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from typing import Any

import pytest
from botocore.exceptions import ClientError

from app.core import storage
from app.core.integrations.openai.video import OpenAIVideoApiAdapter
from app.core.contracts.provider import ProviderConfig
from app.core.contracts.video_generation import VideoGenerationInput


def _client_error(code: str, message: str = "") -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": message}},
        "PutObject",
    )


@pytest.mark.asyncio
async def test_upload_file_retries_without_acl_when_rustfs_rejects_acl(monkeypatch: pytest.MonkeyPatch) -> None:
    """RustFS 不支持 ACL 时，put_object 第一次拒绝、第二次（去 ACL）成功。"""
    calls: list[dict[str, Any]] = []

    class _FakeS3Client:
        def put_object(self, *, Bucket, Key, Body, **extra):  # noqa: ANN001
            calls.append({"Bucket": Bucket, "Key": Key, "extra": dict(extra)})
            if "ACL" in extra:
                raise _client_error("AccessControlListNotSupported", "The bucket does not allow ACLs")
            return {"ETag": "fake-etag"}

    monkeypatch.setattr(storage, "_build_s3_client", lambda: _FakeS3Client())
    monkeypatch.setattr(storage.settings, "s3_bucket_name", "test-bucket")
    monkeypatch.setattr(storage.settings, "s3_base_path", "")
    monkeypatch.setattr(storage.settings, "s3_public_base_url", None)
    monkeypatch.setattr(storage.settings, "s3_endpoint_url", "http://rustfs:9000")

    info = await storage.upload_file(
        key="generated-videos/shots/s1/abc.mp4",
        data=b"video-bytes",
        content_type="video/mp4",
        extra_args={"ACL": "public-read"},
    )

    assert len(calls) == 2, f"expected one retry without ACL, got {len(calls)} calls"
    assert calls[0]["extra"].get("ACL") == "public-read"
    assert "ACL" not in calls[1]["extra"]
    assert info.etag == "fake-etag"
    assert info.url == "http://rustfs:9000/test-bucket/generated-videos/shots/s1/abc.mp4"


@pytest.mark.asyncio
async def test_upload_file_raises_when_acl_error_has_no_acl_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    """非 ACL 相关的 ClientError 必须原样抛出，不能被吞掉。"""

    class _FakeS3Client:
        def put_object(self, *, Bucket, Key, Body, **extra):  # noqa: ANN001
            raise _client_error("AccessDenied", "not allowed")

    monkeypatch.setattr(storage, "_build_s3_client", lambda: _FakeS3Client())
    monkeypatch.setattr(storage.settings, "s3_bucket_name", "test-bucket")
    monkeypatch.setattr(storage.settings, "s3_base_path", "")

    with pytest.raises(ClientError):
        await storage.upload_file(
            key="files/abc.png",
            data=b"x",
            content_type="image/png",
            extra_args={"ACL": "public-read"},
        )


def test_in_process_executor_dedups_same_task_id(monkeypatch, tmp_path) -> None:
    """同一 task_id 并发提交两次，run_task_celery 只应被调用一次。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session, sessionmaker

    from app.core.db import Base
    from app.models.task import GenerationTask
    from app.tasks import execute_task as execute_task_module

    db_path = tmp_path / "dedup.db"
    sync_engine = create_engine(f"sqlite:///{db_path}", future=True)
    sync_session_local = sessionmaker(sync_engine, class_=Session, expire_on_commit=False)

    import app.models.task  # noqa: F401
    Base.metadata.create_all(sync_engine)
    with sync_session_local() as db:
        db.add(
            GenerationTask(
                id="task-dedup",
                mode="async_polling",
                task_kind="video_generation",
                status="running",
                progress=10,
                payload={"task_kind": "video_generation", "run_args": {}},
                result=None,
                error="",
            )
        )
        db.commit()

    runs: list[str] = []
    started = threading.Event()
    release = threading.Event()

    def _fake_run(task_id: str) -> None:
        runs.append(task_id)
        started.set()
        # 阻塞到测试放行，保证第二次提交时 task_id 仍在 _in_process_running 里
        release.wait(timeout=3.0)

    # 让 celery 探活立刻失败，避免 1s 超时把测试拖慢且掩盖去重窗口。
    class _FakeInspect:
        def ping(self):
            return {}

    class _FakeControl:
        def inspect(self, timeout: float = 1.0):
            return _FakeInspect()

    # 真实 celery_app 但控制层被替身覆盖：探活立刻失败 -> 走 in-process 回退。
    # 这样 AsyncResult(task_id, app=celery_app) 仍是合法的真实对象，不会因替身
    # 缺少 backend 属性而炸。
    real_celery_app = execute_task_module.celery_app
    monkeypatch.setattr(real_celery_app, "control", _FakeControl())
    monkeypatch.setattr(execute_task_module, "sync_session_maker", sync_session_local)
    monkeypatch.setattr(execute_task_module, "run_task_celery", _fake_run)

    execute_task_module.enqueue_task_execution("task-dedup")
    # 等到第一次执行真正进入 _fake_run（此时 task_id 已在 _in_process_running）
    assert started.wait(timeout=3.0), "first run did not start"
    execute_task_module.enqueue_task_execution("task-dedup")
    release.set()

    # 给线程池清理 _in_process_running 一点时间
    import time
    time.sleep(0.05)

    assert runs == ["task-dedup"], f"expected single run, got {runs}"
    sync_engine.dispose()


@pytest.mark.asyncio
async def test_openai_video_adapter_retries_on_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """5xx 应重试，最终成功返回 video_id。"""
    import httpx

    responses: list[httpx.Response] = [
        httpx.Response(503, text="upstream down"),
        httpx.Response(503, text="upstream down"),
        httpx.Response(200, json={"id": "vid-abc"}),
    ]
    call_count = {"n": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        resp = responses[call_count["n"]]
        call_count["n"] += 1
        return resp

    transport = httpx.MockTransport(_handler)
    real_async_client = httpx.AsyncClient

    class _PatchedAsyncClient(real_async_client):  # type: ignore[misc]
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("transport", transport)
            super().__init__(*args, **kwargs)

    # adapter 里是 `import httpx` 然后用 httpx.AsyncClient，直接改 httpx 模块上的属性。
    monkeypatch.setattr(httpx, "AsyncClient", _PatchedAsyncClient)
    # 把重试退避压成 0，但要用真实的 asyncio.sleep 避免无限递归。
    import app.core.integrations.openai.video as openai_video_module
    monkeypatch.setattr(openai_video_module, "_CREATE_RETRY_BASE_DELAY", 0.0)

    adapter = OpenAIVideoApiAdapter()
    video_id = await adapter.create_video(
        cfg=ProviderConfig(provider="openai", api_key="k", base_url="https://api.openai.com/v1"),
        input_=VideoGenerationInput(prompt="a cat", ratio="16:9"),
        timeout_s=10.0,
    )

    assert video_id == "vid-abc"
    assert call_count["n"] == 3


@pytest.mark.asyncio
async def test_openai_poll_raises_on_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    """供应商一直不返回终态时，软截止应中断轮询并抛 RuntimeError。"""
    from app.core.tasks.video_generation_tasks import OpenAIVideoGenerationTask

    class _StuckAdapter:
        async def get_video(self, *, cfg, video_id, timeout_s):
            return {"status": "queued"}

    # 拉到非常短的软截止，避免触发 worker 的 120s 硬超时把测试拖到分钟级。
    monkeypatch.setattr(
        "app.core.tasks.video_generation_tasks.AbstractVideoGenerationTask._poll_deadline",
        lambda self: asyncio.get_event_loop().time() + 0.05,
    )

    task = OpenAIVideoGenerationTask(
        provider_config=ProviderConfig(provider="openai", api_key="k", base_url="https://api.openai.com/v1"),
        input_=VideoGenerationInput(prompt="a cat", ratio="16:9"),
        poll_interval_s=0.01,
        timeout_s=0.05,
    )
    task._adapter = _StuckAdapter()
    task._provider_task_id = "vid-stuck"

    with pytest.raises(RuntimeError, match="timed out"):
        await task._poll_and_get_result()
