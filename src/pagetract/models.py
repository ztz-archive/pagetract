"""数据模型与类型定义"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from PIL import Image


# ============================================================
# 页面类型
# ============================================================

class PageType(Enum):
    """PDF 页面类型"""
    SCANNED = "scanned"
    NATIVE = "native"
    MIXED = "mixed"


# ============================================================
# 布局区域类型
# ============================================================

class BlockType(Enum):
    """布局检测区域类型"""
    TITLE = "title"
    TEXT = "text"
    IMAGE = "image"
    TABLE = "table"
    FORMULA = "formula"
    HEADER = "header"
    FOOTER = "footer"
    PAGE_NUMBER = "page_number"
    CAPTION = "caption"
    LIST = "list"
    CODE = "code"
    REFERENCE = "reference"


# ============================================================
# 文本层质量评估
# ============================================================

@dataclass
class TextQualityMetrics:
    """文本层质量评估指标"""
    char_count: int = 0
    invalid_char_ratio: float = 0.0
    cjk_char_ratio: float = 0.0
    font_count: int = 0
    avg_char_width_variance: float = 0.0
    language_coherence: float = 1.0


# ============================================================
# 页面分类
# ============================================================

@dataclass
class PageClassification:
    """单页 PDF 类型分类结果"""
    page_number: int
    page_type: PageType
    text_coverage: float = 0.0
    text_layer_quality: float = 0.0
    quality_metrics: TextQualityMetrics = field(default_factory=TextQualityMetrics)
    quality_reason: str = ""
    has_embedded_images: bool = False
    has_formula_fonts: bool = False
    detected_languages: list[str] = field(default_factory=list)


# ============================================================
# 预处理结果
# ============================================================

@dataclass
class PreprocessResult:
    """页面预处理结果"""
    image: Image.Image
    rotation_applied: int = 0
    skew_corrected: float = 0.0
    was_inverted: bool = False


# ============================================================
# 页面图片
# ============================================================

@dataclass
class PageImage:
    """渲染后的页面图片"""
    page_number: int
    image: Image.Image
    width: int = 0
    height: int = 0
    is_split: bool = False
    split_index: int = 0

    def __post_init__(self):
        if self.width == 0:
            self.width = self.image.width
        if self.height == 0:
            self.height = self.image.height


# ============================================================
# 布局检测
# ============================================================

@dataclass
class LayoutBlock:
    """布局检测到的区域块"""
    block_type: BlockType
    bbox: tuple[int, int, int, int]  # (x1, y1, x2, y2) 像素坐标
    confidence: float = 0.0
    reading_order: int = 0
    page_number: int = 0
    column_id: int | None = None


# ============================================================
# 原生文本提取
# ============================================================

@dataclass
class TextBlock:
    """从原生 PDF 提取的文本块"""
    text: str
    bbox: tuple[int, int, int, int]
    font_size: float = 12.0
    font_name: str = ""
    is_bold: bool = False
    is_italic: bool = False


@dataclass
class EmbeddedImage:
    """PDF 中嵌入的图片"""
    image: Image.Image
    bbox: tuple[int, int, int, int]
    xref: int = 0


@dataclass
class NativeTable:
    """原生表格"""
    bbox: tuple[int, int, int, int]
    cells: list[list[str]] = field(default_factory=list)


@dataclass
class FallbackRegion:
    """需要回退到渲染+VLM 的区域"""
    bbox: tuple[int, int, int, int]
    reason: str  # "formula" | "complex_table" | "garbled_text"


@dataclass
class NativePageContent:
    """原生页面提取内容"""
    page_number: int
    text_blocks: list[TextBlock] = field(default_factory=list)
    embedded_images: list[EmbeddedImage] = field(default_factory=list)
    tables: list[NativeTable] | None = None
    needs_vlm_fallback: list[FallbackRegion] = field(default_factory=list)


# ============================================================
# VLM 识别
# ============================================================

@dataclass
class RecognitionResult:
    """VLM 识别结果"""
    content: str
    content_type: str = "text"  # "text" | "latex" | "markdown_table" | "html_table"
    confidence: float | None = None
    target_bbox: tuple[int, int, int, int] = (0, 0, 0, 0)
    raw_response: str = ""
    validation_passed: bool = True
    validation_warning: str = ""


# ============================================================
# 处理后的区域结果
# ============================================================

@dataclass
class ProcessedBlock:
    """处理完成的区域（VLM 识别后或原生提取后）"""
    block_type: BlockType
    bbox: tuple[int, int, int, int]
    page_number: int
    reading_order: int = 0
    content: str = ""
    content_type: str = "text"
    image_path: str | None = None  # 图片区域保存路径
    confidence: float | None = None
    source: str = "vlm"  # "vlm" | "native" | "cache"
    validation_passed: bool = True
    validation_warning: str = ""


# ============================================================
# 跨页合并
# ============================================================

@dataclass
class CrossPagePair:
    """跨页元素对"""
    block1: ProcessedBlock
    block2: ProcessedBlock
    merge_type: str  # "table" | "paragraph" | "formula"


# ============================================================
# 转换结果
# ============================================================

@dataclass
class ConversionMetadata:
    """转换元数据"""
    total_pages: int = 0
    processing_time_seconds: float = 0.0
    api_calls: int = 0
    estimated_cost_yuan: float = 0.0
    page_types: dict[str, int] = field(default_factory=dict)
    cache_hits: dict[str, int] = field(default_factory=lambda: {"layout": 0, "vlm": 0})
    blocks_per_page: dict[int, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass
class ConversionResult:
    """最终转换结果"""
    markdown: str = ""
    images: list[dict[str, Any]] = field(default_factory=list)
    metadata: ConversionMetadata = field(default_factory=ConversionMetadata)
    output_dir: str = ""


@dataclass
class CostEstimate:
    """成本预估"""
    total_pages: int = 0
    page_types: dict[str, int] = field(default_factory=dict)
    estimated_api_calls: int = 0
    estimated_cost_yuan: float = 0.0
    estimated_time_seconds: float = 0.0
