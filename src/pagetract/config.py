"""配置系统：Pydantic 模型 + YAML 加载 + 环墩变量"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


# ============================================================
# 分模块配置
# ============================================================

class GeneralConfig(BaseModel):
    render_dpi: int = 300
    page_range: list[int] | None = None
    output_dir: str = "./output"
    document_context: str = ""


class PDFDetectionConfig(BaseModel):
    force_mode: str | None = None
    text_quality_threshold: float = 0.7
    min_text_chars: int = 20
    formula_font_patterns: list[str] = Field(
        default=["CMMI", "CMBX", "Cambria Math", "STIXGeneral"]
    )


class PreprocessingConfig(BaseModel):
    enable_rotation_correction: bool = True
    enable_deskew: bool = True
    deskew_threshold_degrees: float = 0.5
    enable_inversion_detection: bool = True


class LayoutConfig(BaseModel):
    engine: str = "doclayout-yolo"
    confidence_threshold: float = 0.5
    merge_adjacent_text: bool = True
    detect_reading_order: bool = True
    detect_columns: bool = True
    discard_types: list[str] = Field(default=["header", "footer", "page_number"])


class VLMConfig(BaseModel):
    provider: str = "dashscope"
    api_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    api_key: str = ""
    model: str = "qwen3.5-plus"
    temperature: float = 0.1
    max_concurrent: int = 15
    connection_pool_size: int = 20
    max_retries: int = 3
    timeout: int = 60
    recognition_mode: str = "full_page"  # "full_page" | "crop"
    vlm_downsample_ratio: float = 0.7
    batch_regions: bool = True
    max_regions_per_batch: int = 5
    max_region_distance: int = 500
    complexity_threshold: int = 15
    enable_output_validation: bool = False
    generate_image_alt: bool = True
    custom_prompts: dict[str, str] = Field(default_factory=dict)
    document_context: str = ""


class ImageExtractionConfig(BaseModel):
    format: str = "png"
    quality: int = 95
    min_size: int = 50
    padding: int = 5
    save_table_images: bool = True
    prefer_embedded: bool = True


class RenderConfig(BaseModel):
    render_dpi: int = 300
    image_format: str = "png"
    max_page_height_px: int = 4000
    split_height: int = 3200
    split_overlap: int = 200


class CacheConfig(BaseModel):
    enable: bool = True
    directory: str = "./cache"
    max_size_mb: int = 500
    eviction_policy: str = "lru"
    layout_cache_ttl_hours: int = 24
    vlm_cache_ttl_days: int = 7
    document_cache_ttl_days: int = 30


class MarkdownConfig(BaseModel):
    page_separator: str = "\n\n---\n\n"
    include_page_markers: bool = True
    include_source_markers: bool = True
    image_ref_style: str = "relative"  # "relative" | "absolute" | "base64_inline"
    title_level_strategy: str = "auto"  # "auto" | "flat" | "positional"
    discard_header_footer: bool = True


class CostControlConfig(BaseModel):
    enable_cost_estimation: bool = True
    budget_limit_yuan: float | None = None


class APIConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 34045
    max_file_size_mb: int = 100
    max_pages: int = 200
    async_threshold_pages: int = 10
    task_ttl_hours: int = 24


class MemoryConfig(BaseModel):
    max_cached_pages: int = 3


class NativeExtractConfig(BaseModel):
    fallback_to_vlm: bool = True
    formula_font_patterns: list[str] = Field(
        default=["CMMI", "CMBX", "Cambria Math"]
    )
    garbled_text_threshold: float = 0.05


class VideoConfig(BaseModel):
    download_dir: str = "./cache/video"
    cookies_from_browser: str | None = None

    # 音频转录 (STT)
    stt_model: str = "sensevoice-v1"
    stt_api_base_url: str = ""    # 空 = 复用 vlm.api_base_url
    stt_api_key: str = ""          # 空 = 复用 vlm.api_key
    audio_format: str = "mp3"
    audio_chunk_seconds: int = 600  # 10 分钟一段

    # 视频理解
    video_model: str = ""           # 空 = 复用 vlm.model
    max_key_frames: int = 20
    frame_interval_seconds: int = 30

    # Prompt
    understanding_prompt: str = (
        "以下是视频《{title}》的 {num_frames} 个等间距关键帧截图\uff08视频时长约 {duration} 秒\uff09。\n"
        "视频简介\uff1a{description}\n\n"
        "请基于这些关键帧\uff0c详细分析并描述视频的完整内容\uff0c包括\uff1a\n"
        "1. 视频的主题和核心内容\n"
        "2. 视频中出现的关键信息\uff08文字、数据、图表、代码等\uff09\n"
        "3. 视频的结构和叙事顺序\n"
        "4. 重要的视觉元素和场景\n\n"
        "请以结构化的 Markdown 格式输出\uff0c使用适当的标题层级组织内容。"
    )


# ============================================================
# 根配置
# ============================================================

class PagetractConfig(BaseModel):
    general: GeneralConfig = Field(default_factory=GeneralConfig)
    pdf_detection: PDFDetectionConfig = Field(default_factory=PDFDetectionConfig)
    preprocessing: PreprocessingConfig = Field(default_factory=PreprocessingConfig)
    layout: LayoutConfig = Field(default_factory=LayoutConfig)
    vlm: VLMConfig = Field(default_factory=VLMConfig)
    image_extraction: ImageExtractionConfig = Field(default_factory=ImageExtractionConfig)
    render: RenderConfig = Field(default_factory=RenderConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    markdown: MarkdownConfig = Field(default_factory=MarkdownConfig)
    cost_control: CostControlConfig = Field(default_factory=CostControlConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    native_extract: NativeExtractConfig = Field(default_factory=NativeExtractConfig)
    video: VideoConfig = Field(default_factory=VideoConfig)


# ============================================================
# 配置加载
# ============================================================

def _resolve_env_vars(data: Any) -> Any:
    """递归替换配置中的 ${ENV_VAR} 引用"""
    if isinstance(data, str) and data.startswith("${") and data.endswith("}"):
        env_name = data[2:-1]
        return os.environ.get(env_name, "")
    if isinstance(data, dict):
        return {k: _resolve_env_vars(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_resolve_env_vars(v) for v in data]
    return data


def load_config(
    config_path: str | Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> PagetractConfig:
    """加载配置：YAML 文件 + 环境变量 + 覆盖参数

    优先级: overrides > 环境变量 > config.yaml > 默认值
    """
    data: dict[str, Any] = {}

    # 1. 从 YAML 文件加载
    if config_path is None:
        config_path = os.environ.get("SCANDOC_CONFIG", "./config.yaml")
    config_path = Path(config_path)

    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
            if isinstance(raw, dict):
                data = raw

    # 1.1 加载环境覆盖文件 (config.dev.yaml / config.prod.yaml)
    env = os.environ.get("SCANDOC_ENV", "")
    if env:
        env_config_path = config_path.parent / f"config.{env}.yaml"
        if env_config_path.exists():
            with open(env_config_path, encoding="utf-8") as f:
                env_data = yaml.safe_load(f)
                if isinstance(env_data, dict):
                    _deep_merge(data, env_data)

    # 2. 解析环境变量引用
    data = _resolve_env_vars(data)

    # 3. 从环境变量映射关键项
    env_mappings = {
        "SCANDOC_API_KEY": ("vlm", "api_key"),
        "SCANDOC_SERVER_HOST": ("api", "host"),
        "SCANDOC_SERVER_PORT": ("api", "port"),
    }
    for env_key, (section, field) in env_mappings.items():
        val = os.environ.get(env_key)
        if val is not None:
            data.setdefault(section, {})[field] = val

    # 4. 应用覆盖
    if overrides:
        _deep_merge(data, overrides)

    return PagetractConfig(**data)


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并字典"""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def save_config(config: PagetractConfig, path: str | Path) -> None:
    """保存配置到 YAML"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = config.model_dump()
    # 不保存 api_key 明文
    if data.get("vlm", {}).get("api_key"):
        data["vlm"]["api_key"] = "${SCANDOC_API_KEY}"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
