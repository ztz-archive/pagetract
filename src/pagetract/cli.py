"""CLI 命令行接口 — 基于 Typer"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

app = typer.Typer(
    name="pagetract",
    help="pagetract — 让大模型读懂一切文档",
    no_args_is_help=True,
)
console = Console()


# ============================================================
# convert 子命令
# ============================================================

@app.command()
def convert(
    input_path: str = typer.Argument(..., help="PDF 文件或目录路径"),
    output_dir: Optional[str] = typer.Option(None, "-o", "--output", help="输出目录"),
    config: Optional[str] = typer.Option(None, "--config", help="配置文件路径"),
    model: Optional[str] = typer.Option(None, "--model", help="VLM 模型名称"),
    dpi: Optional[int] = typer.Option(None, "--dpi", help="渲染 DPI"),
    pages: Optional[str] = typer.Option(None, "--pages", help="页码范围 (如 1-5,8,10)"),
    force_mode: Optional[str] = typer.Option(None, "--force-mode", help="强制模式: scanned/native"),
    dry_run: bool = typer.Option(False, "--dry-run", help="仅预估成本，不执行转换"),
    layout_only: bool = typer.Option(False, "--layout-only", help="仅做布局检测"),
    batch: bool = typer.Option(False, "--batch", help="批量处理目录"),
    recursive: bool = typer.Option(False, "--recursive", help="递归子目录"),
    max_cost: Optional[float] = typer.Option(None, "--max-cost", help="最大预算(元)"),
    no_cache: bool = typer.Option(False, "--no-cache", help="禁用缓存"),
    output_format: str = typer.Option("markdown", "--output-format", help="输出格式: markdown/json"),
    log_level: str = typer.Option("info", "--log-level", help="日志级别"),
    log_file: Optional[str] = typer.Option(None, "--log-file", help="日志文件路径"),
):
    """转换 PDF 文档为 Markdown"""
    import logging

    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        filename=log_file,
    )

    from pagetract.config import load_config

    # 构建配置覆盖
    overrides: dict = {}
    if model:
        overrides.setdefault("vlm", {})["model"] = model
    if dpi:
        overrides.setdefault("general", {})["render_dpi"] = dpi
        overrides.setdefault("render", {})["render_dpi"] = dpi
    if force_mode:
        overrides.setdefault("pdf_detection", {})["force_mode"] = force_mode
    if max_cost is not None:
        overrides.setdefault("cost_control", {})["budget_limit_yuan"] = max_cost
    if no_cache:
        overrides.setdefault("cache", {})["enable"] = False
    if pages:
        page_list = _parse_page_range(pages)
        overrides.setdefault("general", {})["page_range"] = page_list

    cfg = load_config(config_path=config, overrides=overrides if overrides else None)
    output_dir = output_dir or cfg.general.output_dir

    input_p = Path(input_path)

    if batch and input_p.is_dir():
        _batch_convert(input_p, output_dir, cfg, recursive)
        return

    if not input_p.exists():
        console.print(f"[red]Error:[/red] File not found: {input_path}")
        raise typer.Exit(1)

    if not input_p.suffix.lower() == ".pdf":
        console.print(f"[red]Error:[/red] Not a PDF file: {input_path}")
        raise typer.Exit(1)

    from pagetract.core.pipeline import Pipeline
    pipeline = Pipeline(cfg)

    # Dry-run: 仅预估
    if dry_run:
        estimate = pipeline.estimate(str(input_p))
        _print_estimate(estimate)
        return

    # 正常转换
    console.print(f"Processing: [bold]{input_p.name}[/bold]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Converting...", total=None)

        def on_progress(info: dict):
            stage = info.get("stage", "")
            current = info.get("current_page", 0)
            total = info.get("total_pages", 0)
            if total > 0:
                progress.update(task, total=total, completed=current, description=stage)
            else:
                progress.update(task, description=stage)

        pipeline.set_progress_callback(on_progress)
        result = pipeline.convert(str(input_p), output_dir)

    # 输出结果
    console.print()
    _print_result(result, output_format)


# ============================================================
# serve 子命令
# ============================================================

@app.command()
def serve(
    port: int = typer.Option(34045, "--port", help="监听端口"),
    host: str = typer.Option("0.0.0.0", "--host", help="监听地址"),
    config: Optional[str] = typer.Option(None, "--config", help="配置文件路径"),
):
    """启动 API 服务"""
    import uvicorn
    from pagetract.config import load_config

    overrides = {"api": {"host": host, "port": port}}
    cfg = load_config(config_path=config, overrides=overrides)

    console.print(f"Starting API server at [bold]http://{host}:{port}[/bold]")
    console.print("Docs at [bold]http://{host}:{port}/docs[/bold]")

    from pagetract.api.app import create_app
    api_app = create_app(cfg)
    uvicorn.run(api_app, host=host, port=port)


# ============================================================
# video 子命令
# ============================================================

@app.command()
def video(
    url: str = typer.Argument(..., help="B站视频 URL"),
    output_dir: Optional[str] = typer.Option(None, "-o", "--output", help="输出目录"),
    config: Optional[str] = typer.Option(None, "--config", help="配置文件路径"),
    audio_only: bool = typer.Option(False, "--audio-only", help="仅音频转录"),
    video_only: bool = typer.Option(False, "--video-only", help="仅视频理解"),
    model: Optional[str] = typer.Option(None, "--model", help="VLM 模型名称"),
    stt_model: Optional[str] = typer.Option(None, "--stt-model", help="STT 模型名称"),
    max_frames: Optional[int] = typer.Option(None, "--max-frames", help="最大关键帧数"),
    frame_interval: Optional[int] = typer.Option(None, "--frame-interval", help="关键帧间隔(秒)"),
    log_level: str = typer.Option("info", "--log-level", help="日志级别"),
):
    """将B站视频转换为文字（音频转录 + 视频理解）"""
    import asyncio
    import logging

    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    from pagetract.config import load_config

    overrides: dict = {}
    if model:
        overrides.setdefault("vlm", {})["model"] = model
    if stt_model:
        overrides.setdefault("video", {})["stt_model"] = stt_model
    if max_frames is not None:
        overrides.setdefault("video", {})["max_key_frames"] = max_frames
    if frame_interval is not None:
        overrides.setdefault("video", {})["frame_interval_seconds"] = frame_interval

    cfg = load_config(config_path=config, overrides=overrides if overrides else None)
    output_dir = output_dir or cfg.general.output_dir

    from pagetract.core.video_processor import VideoProcessor

    processor = VideoProcessor(cfg.video, cfg.vlm)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Processing video...", total=None)

        def on_progress(info: dict):
            stage = info.get("stage", "")
            progress.update(task, description=stage)

        processor.set_progress_callback(on_progress)

        result = asyncio.get_event_loop().run_until_complete(
            processor.process(url, output_dir, audio_only=audio_only, video_only=video_only)
        )

    # 输出结果
    console.print()
    title = result.video_info.get("title", "unknown")
    console.print(f"[bold green]Done![/bold green]  Video: {title}")
    console.print()

    table = Table(title="Video Conversion Results")
    table.add_column("Output")
    table.add_column("Path")

    if result.audio_markdown_path:
        table.add_row("Audio transcript", result.audio_markdown_path)
    if result.video_markdown_path:
        table.add_row("Video understanding", result.video_markdown_path)

    console.print(table)


# ============================================================
# config 子命令
# ============================================================

config_app = typer.Typer(help="配置管理")
app.add_typer(config_app, name="config")


@config_app.command("init")
def config_init():
    """交互式初始化配置文件"""
    from pagetract.config import PagetractConfig, save_config

    output_path = Path("config.yaml")
    if output_path.exists():
        overwrite = typer.confirm("config.yaml already exists. Overwrite?", default=False)
        if not overwrite:
            console.print("Cancelled.")
            return

    cfg = PagetractConfig()

    # 交互式配置关键项
    provider = typer.prompt("VLM Provider", default="dashscope")
    model = typer.prompt("VLM Model", default="qwen3.5-plus")
    api_base = typer.prompt(
        "API Base URL",
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    render_dpi = typer.prompt("Render DPI", default=300, type=int)

    cfg.vlm.provider = provider
    cfg.vlm.model = model
    cfg.vlm.api_base_url = api_base
    cfg.general.render_dpi = render_dpi
    cfg.render.render_dpi = render_dpi

    save_config(cfg, output_path)
    console.print(f"[green]Config saved to {output_path}[/green]")
    console.print("[yellow]Remember to set SCANDOC_API_KEY environment variable![/yellow]")


@config_app.command("show")
def config_show(config: Optional[str] = typer.Option(None, "--config", help="配置文件路径")):
    """显示当前生效的配置"""
    from pagetract.config import load_config
    cfg = load_config(config_path=config)
    import yaml
    console.print(yaml.dump(cfg.model_dump(), default_flow_style=False, allow_unicode=True))


@config_app.command("validate")
def config_validate(config: Optional[str] = typer.Option(None, "--config", help="配置文件路径")):
    """校验配置合法性"""
    try:
        from pagetract.config import load_config
        cfg = load_config(config_path=config)
        console.print("[green]✅ Configuration is valid[/green]")

        if not cfg.vlm.api_key:
            console.print("[yellow]⚠️ VLM API key not set (set SCANDOC_API_KEY)[/yellow]")
    except Exception as e:
        console.print(f"[red]❌ Configuration error: {e}[/red]")
        raise typer.Exit(1)


# ============================================================
# doctor 子命令
# ============================================================

@app.command()
def doctor():
    """检查环境和依赖"""
    checks = []

    # Python
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    checks.append(("Python", py_ver, True))

    # PyMuPDF
    try:
        import fitz
        checks.append(("PyMuPDF", fitz.version[0], True))
    except ImportError:
        checks.append(("PyMuPDF", "not installed", False))

    # Pillow
    try:
        from PIL import Image
        import PIL
        checks.append(("Pillow", PIL.__version__, True))
    except ImportError:
        checks.append(("Pillow", "not installed", False))

    # DocLayout-YOLO
    try:
        import doclayout_yolo
        checks.append(("DocLayout-YOLO", "available", True))
    except ImportError:
        checks.append(("DocLayout-YOLO", "not installed (optional)", None))

    # httpx
    try:
        import httpx
        checks.append(("httpx", httpx.__version__, True))
    except ImportError:
        checks.append(("httpx", "not installed", False))

    # FastAPI
    try:
        import fastapi
        checks.append(("FastAPI", fastapi.__version__, True))
    except ImportError:
        checks.append(("FastAPI", "not installed (optional)", None))

    # Gradio
    try:
        import gradio
        checks.append(("Gradio", gradio.__version__, True))
    except ImportError:
        checks.append(("Gradio", "not installed (optional)", None))

    # Tesseract
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        checks.append(("Tesseract", "available", True))
    except Exception:
        checks.append(("Tesseract", "not installed (rotation detection unavailable)", None))

    # deskew
    try:
        import deskew
        checks.append(("deskew", "available", True))
    except ImportError:
        checks.append(("deskew", "not installed (deskew unavailable)", None))

    # yt-dlp (video feature)
    import shutil
    if shutil.which("yt-dlp"):
        checks.append(("yt-dlp", "available", True))
    else:
        checks.append(("yt-dlp", "not installed (video feature unavailable)", None))

    # ffmpeg (video feature)
    if shutil.which("ffmpeg"):
        checks.append(("ffmpeg", "available", True))
    else:
        checks.append(("ffmpeg", "not installed (video/audio processing unavailable)", None))

    # VLM API
    try:
        from pagetract.config import load_config
        cfg = load_config()
        if cfg.vlm.api_key:
            checks.append(("VLM API Key", f"configured ({cfg.vlm.provider})", True))
        else:
            checks.append(("VLM API Key", "not set", None))
    except Exception:
        checks.append(("VLM API Key", "config error", False))

    # GPU
    try:
        import torch
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            checks.append(("GPU", f"available ({gpu_name})", True))
        else:
            checks.append(("GPU", "not available", None))
    except ImportError:
        checks.append(("GPU (PyTorch)", "not installed", None))

    # 输出
    table = Table(title="Environment Check")
    table.add_column("Component", style="cyan")
    table.add_column("Status")
    table.add_column("")

    for name, status, ok in checks:
        if ok is True:
            icon = "✅"
            style = "green"
        elif ok is False:
            icon = "❌"
            style = "red"
        else:
            icon = "⚠️"
            style = "yellow"
        table.add_row(name, f"[{style}]{status}[/{style}]", icon)

    console.print(table)


# ============================================================
# version 子命令
# ============================================================

@app.command()
def version():
    """显示版本信息"""
    from pagetract import __version__
    console.print(f"pagetract v{__version__}")


# ============================================================
# 辅助函数
# ============================================================

def _parse_page_range(pages_str: str) -> list[int]:
    """解析页码范围字符串 '1-5,8,10' → [1,2,3,4,5,8,10]"""
    result: list[int] = []
    for part in pages_str.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            result.extend(range(int(start), int(end) + 1))
        else:
            result.append(int(part))
    return sorted(set(result))


def _print_estimate(estimate):
    """打印成本预估"""
    table = Table(title="Cost Estimate")
    table.add_column("Metric")
    table.add_column("Value", justify="right")

    table.add_row("Total Pages", str(estimate.total_pages))
    for ptype, count in estimate.page_types.items():
        table.add_row(f"  {ptype}", str(count))
    table.add_row("Estimated API Calls", str(estimate.estimated_api_calls))
    table.add_row("Estimated Cost", f"¥{estimate.estimated_cost_yuan:.2f}")
    table.add_row("Estimated Time", f"{estimate.estimated_time_seconds:.1f}s")

    console.print(table)


def _print_result(result, output_format: str = "markdown"):
    """打印转换结果"""
    meta = result.metadata

    table = Table(title="Results")
    table.add_column("Metric")
    table.add_column("Value", justify="right")

    table.add_row("Output", result.output_dir)
    table.add_row("Images", str(len(result.images)))
    table.add_row("Total Time", f"{meta.processing_time_seconds:.1f}s")
    table.add_row("API Calls", str(meta.api_calls))
    table.add_row("Est. Cost", f"¥{meta.estimated_cost_yuan:.2f}")

    for ptype, count in meta.page_types.items():
        table.add_row(f"  {ptype} pages", str(count))

    cache_hits = meta.cache_hits
    table.add_row("Cache Hits (layout)", str(cache_hits.get("layout", 0)))
    table.add_row("Cache Hits (vlm)", str(cache_hits.get("vlm", 0)))

    if meta.errors:
        table.add_row("Errors", str(len(meta.errors)))

    console.print(table)

    if output_format == "json":
        console.print_json(json.dumps(meta.__dict__, default=str, ensure_ascii=False))

    console.print("\n[green]Done.[/green]")


def _batch_convert(input_dir: Path, output_dir: str, cfg, recursive: bool):
    """批量转换目录中的 PDF"""
    from pagetract.core.pipeline import Pipeline

    pattern = "**/*.pdf" if recursive else "*.pdf"
    pdfs = list(input_dir.glob(pattern))

    if not pdfs:
        console.print("[yellow]No PDF files found[/yellow]")
        return

    console.print(f"Found [bold]{len(pdfs)}[/bold] PDF files")

    pipeline = Pipeline(cfg)
    for i, pdf in enumerate(pdfs, 1):
        console.print(f"\n[{i}/{len(pdfs)}] {pdf.name}")
        out = Path(output_dir) / pdf.stem
        try:
            result = pipeline.convert(str(pdf), str(out))
            console.print(f"  [green]✅ Done[/green] ({result.metadata.processing_time_seconds:.1f}s)")
        except Exception as e:
            console.print(f"  [red]❌ Failed: {e}[/red]")


if __name__ == "__main__":
    app()
