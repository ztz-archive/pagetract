"""FastAPI 应用 — RESTful API + SSE 实时进度"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from pagetract import __version__
from pagetract.config import PagetractConfig, load_config
from pagetract.core.pipeline import Pipeline
from pagetract.models import ConversionResult

# ============================================================
# 任务存储
# ============================================================

_tasks: dict[str, dict[str, Any]] = {}
_task_events: dict[str, asyncio.Queue] = {}


def _get_task(task_id: str) -> dict[str, Any]:
    if task_id not in _tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    return _tasks[task_id]


# ============================================================
# App 工厂
# ============================================================

def create_app(config: PagetractConfig | None = None) -> FastAPI:
    if config is None:
        config = load_config()

    app = FastAPI(
        title="pagetract API",
        description="高精度 PDF 文档转 Markdown API 服务",
        version=__version__,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.config = config
    app.state.pipeline = Pipeline(config)

    _register_routes(app)
    return app


# ============================================================
# 路由注册
# ============================================================

def _register_routes(app: FastAPI):

    # --------------------------------------------------------
    # 健康检查
    # --------------------------------------------------------

    @app.get("/api/v1/health")
    async def health():
        cfg = app.state.config
        return {
            "status": "ok",
            "version": __version__,
            "layout_engine": cfg.layout.engine,
            "vlm_provider": cfg.vlm.provider,
            "vlm_model": cfg.vlm.model,
        }

    # --------------------------------------------------------
    # 文档转换
    # --------------------------------------------------------

    @app.post("/api/v1/convert")
    async def convert(
        file: UploadFile = File(...),
        config: str | None = Form(None),
        page_range: str | None = Form(None),
        callback_url: str | None = Form(None),
    ):
        cfg: PagetractConfig = app.state.config

        # 验证文件
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=415, detail="Only PDF files are supported")

        content = await file.read()
        file_size_mb = len(content) / (1024 * 1024)
        if file_size_mb > cfg.api.max_file_size_mb:
            raise HTTPException(status_code=413, detail=f"File too large ({file_size_mb:.1f}MB > {cfg.api.max_file_size_mb}MB)")

        # 保存临时文件
        task_id = str(uuid.uuid4())
        task_dir = Path(tempfile.gettempdir()) / "pagetract" / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = task_dir / "input.pdf"
        pdf_path.write_bytes(content)
        output_dir = task_dir / "output"

        # 解析配置覆盖
        overrides: dict = {}
        if config:
            try:
                overrides = json.loads(config)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid config JSON")

        if page_range:
            from pagetract.cli import _parse_page_range
            overrides.setdefault("general", {})["page_range"] = _parse_page_range(page_range)

        # 创建任务
        _tasks[task_id] = {
            "task_id": task_id,
            "status": "processing",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "pdf_path": str(pdf_path),
            "output_dir": str(output_dir),
            "result": None,
            "error": None,
            "callback_url": callback_url,
        }
        _task_events[task_id] = asyncio.Queue()

        # 检查页数 → 同步/异步模式
        import fitz
        doc = fitz.open(str(pdf_path))
        num_pages = len(doc)
        doc.close()

        if num_pages > cfg.api.max_pages:
            raise HTTPException(status_code=400, detail=f"Too many pages ({num_pages} > {cfg.api.max_pages})")

        if num_pages <= cfg.api.async_threshold_pages:
            # 同步模式
            try:
                pipeline: Pipeline = app.state.pipeline
                result = await pipeline.aconvert(str(pdf_path), str(output_dir))
                _tasks[task_id]["status"] = "completed"
                _tasks[task_id]["result"] = _format_result(task_id, result)
                return {
                    "task_id": task_id,
                    "status": "completed",
                    "result": _tasks[task_id]["result"],
                }
            except Exception as e:
                _tasks[task_id]["status"] = "failed"
                _tasks[task_id]["error"] = str(e)
                raise HTTPException(status_code=500, detail=str(e))
        else:
            # 异步模式
            asyncio.create_task(_process_async(app, task_id, overrides))
            return JSONResponse(
                status_code=202,
                content={
                    "task_id": task_id,
                    "status": "processing",
                    "events_url": f"/api/v1/tasks/{task_id}/events",
                },
            )

    # --------------------------------------------------------
    # 任务状态
    # --------------------------------------------------------

    @app.get("/api/v1/tasks/{task_id}")
    async def get_task(task_id: str):
        task = _get_task(task_id)
        return {
            "task_id": task_id,
            "status": task["status"],
            "result": task.get("result"),
            "error": task.get("error"),
        }

    # --------------------------------------------------------
    # SSE 进度推送
    # --------------------------------------------------------

    @app.get("/api/v1/tasks/{task_id}/events")
    async def task_events(task_id: str):
        _get_task(task_id)

        async def event_generator():
            queue = _task_events.get(task_id)
            if not queue:
                yield f"event: error\ndata: {{\"message\": \"No event queue\"}}\n\n"
                return

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    if event is None:
                        break
                    event_type = event.get("type", "progress")
                    data = json.dumps(event.get("data", {}), ensure_ascii=False)
                    yield f"event: {event_type}\ndata: {data}\n\n"

                    if event_type in ("completed", "failed"):
                        break
                except asyncio.TimeoutError:
                    yield f"event: heartbeat\ndata: {{}}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # --------------------------------------------------------
    # 任务取消
    # --------------------------------------------------------

    @app.delete("/api/v1/tasks/{task_id}")
    async def cancel_task(task_id: str):
        task = _get_task(task_id)
        task["status"] = "cancelled"
        return {
            "status": "cancelled",
            "cancelled_at": datetime.now(timezone.utc).isoformat(),
        }

    # --------------------------------------------------------
    # 获取结果
    # --------------------------------------------------------

    @app.get("/api/v1/tasks/{task_id}/result")
    async def get_result(task_id: str):
        task = _get_task(task_id)
        if task["status"] != "completed":
            raise HTTPException(status_code=400, detail=f"Task is {task['status']}")
        return task["result"]

    # --------------------------------------------------------
    # 下载结果文件
    # --------------------------------------------------------

    @app.get("/api/v1/files/{task_id}/document.md")
    async def download_markdown(task_id: str):
        task = _get_task(task_id)
        md_path = Path(task["output_dir"]) / "document.md"
        if not md_path.exists():
            raise HTTPException(status_code=404, detail="Document not found")
        return FileResponse(md_path, media_type="text/markdown", filename="document.md")

    @app.get("/api/v1/files/{task_id}/images/{filename}")
    async def download_image(task_id: str, filename: str):
        task = _get_task(task_id)
        # 防止路径遍历
        safe_name = Path(filename).name
        img_path = Path(task["output_dir"]) / "images" / safe_name
        if not img_path.exists():
            raise HTTPException(status_code=404, detail="Image not found")
        return FileResponse(img_path)

    @app.get("/api/v1/files/{task_id}/result.zip")
    async def download_zip(task_id: str):
        task = _get_task(task_id)
        output_dir = Path(task["output_dir"])
        if not output_dir.exists():
            raise HTTPException(status_code=404, detail="Output not found")

        zip_path = output_dir.parent / "result.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in output_dir.rglob("*"):
                if f.is_file():
                    zf.write(f, f.relative_to(output_dir))

        return FileResponse(zip_path, media_type="application/zip", filename="result.zip")

    # --------------------------------------------------------
    # 成本预估
    # --------------------------------------------------------

    @app.post("/api/v1/estimate")
    async def estimate(file: UploadFile = File(...)):
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=415, detail="Only PDF files are supported")

        content = await file.read()
        tmp = Path(tempfile.mktemp(suffix=".pdf"))
        tmp.write_bytes(content)

        try:
            pipeline: Pipeline = app.state.pipeline
            est = pipeline.estimate(str(tmp))
            return {
                "total_pages": est.total_pages,
                "page_types": est.page_types,
                "estimated_api_calls": est.estimated_api_calls,
                "estimated_cost_yuan": est.estimated_cost_yuan,
                "estimated_time_seconds": est.estimated_time_seconds,
            }
        finally:
            tmp.unlink(missing_ok=True)

    # --------------------------------------------------------
    # 配置预检
    # --------------------------------------------------------

    @app.post("/api/v1/validate_config")
    async def validate_config(config_json: dict | None = None):
        try:
            cfg = app.state.config
            checks = {
                "api_key_set": bool(cfg.vlm.api_key),
                "model": cfg.vlm.model,
                "provider": cfg.vlm.provider,
            }
            return {"valid": True, "checks": checks}
        except Exception as e:
            return {"valid": False, "error": str(e)}

    # --------------------------------------------------------
    # 统一错误处理
    # --------------------------------------------------------

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request, exc):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.status_code,
                    "message": exc.detail,
                    "detail": None,
                }
            },
        )


# ============================================================
# 异步处理
# ============================================================

async def _process_async(app: FastAPI, task_id: str, overrides: dict):
    """后台异步处理任务"""
    task = _tasks[task_id]
    queue = _task_events.get(task_id)
    pipeline: Pipeline = app.state.pipeline

    def on_progress(info: dict):
        if queue and task["status"] != "cancelled":
            try:
                queue.put_nowait({
                    "type": "progress",
                    "data": info,
                })
            except asyncio.QueueFull:
                pass

    pipeline.set_progress_callback(on_progress)

    try:
        if task["status"] == "cancelled":
            return

        result = await pipeline.aconvert(task["pdf_path"], task["output_dir"])
        task["status"] = "completed"
        task["result"] = _format_result(task_id, result)

        if queue:
            await queue.put({
                "type": "completed",
                "data": {
                    "task_id": task_id,
                    "result_url": f"/api/v1/tasks/{task_id}/result",
                },
            })

        # 回调
        if task.get("callback_url"):
            import httpx
            async with httpx.AsyncClient() as client:
                try:
                    await client.post(
                        task["callback_url"],
                        json={"task_id": task_id, "status": "completed"},
                        timeout=10,
                    )
                except Exception:
                    pass

    except Exception as e:
        task["status"] = "failed"
        task["error"] = str(e)
        if queue:
            await queue.put({
                "type": "failed",
                "data": {"task_id": task_id, "error": str(e)},
            })
    finally:
        if queue:
            await queue.put(None)  # 信号结束


def _format_result(task_id: str, result: ConversionResult) -> dict[str, Any]:
    """格式化转换结果为 API 响应"""
    images = []
    for img in result.images:
        images.append({
            "filename": img["filename"],
            "url": f"/api/v1/files/{task_id}/images/{img['filename']}",
            "width": img.get("width", 0),
            "height": img.get("height", 0),
        })

    return {
        "markdown": result.markdown,
        "images": images,
        "metadata": {
            "total_pages": result.metadata.total_pages,
            "processing_time_seconds": result.metadata.processing_time_seconds,
            "api_calls": result.metadata.api_calls,
            "estimated_cost_yuan": result.metadata.estimated_cost_yuan,
            "page_types": result.metadata.page_types,
            "cache_hits": result.metadata.cache_hits,
        },
    }
