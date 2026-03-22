# ScanDoc2MD — 基于混合架构的高精度 PDF 文档转 Markdown 系统

## 项目需求文档 v2.0

**变更记录**：

| 版本 | 日期 | 主要变更 |
|------|------|----------|
| v1.0 | — | 初版，聚焦扫描件 PDF |
| v2.0 | 2026-03-22 | 扩展为通用 PDF 处理（扫描件 + 原生 + 混合型）；新增 API 服务与 Demo 网站 |

---

## 1. 项目概述

### 1.1 项目定位

ScanDoc2MD 是一个开源的文档处理工具，专注于将**各类 PDF 文档**高精度地转换为带图片引用的结构化 Markdown 文档。

支持的 PDF 类型包括但不限于：

| PDF 类型 | 说明 | 处理策略 |
|----------|------|----------|
| **纯扫描件 PDF** | 整页都是图片，无文本层 | 渲染为图片 → CV 布局检测 → VLM 识别 |
| **原生数字 PDF** | 有完整文本层、矢量图形 | 优先提取文本层；图片/表格/公式仍走 CV + VLM |
| **图文混合 PDF** | 部分页有文本层，部分页是扫描图 | 逐页判断，自适应选择策略 |
| **学术论文 PDF** | 双栏/多栏排版，含公式、表格、引用 | 布局检测处理多栏，VLM 识别公式与表格 |
| **报告/书籍 PDF** | 图文混排，含页眉页脚、目录 | 完整区域检测与分类 |

### 1.2 核心设计理念

采用**"CV 定位 + VLM 全页理解"的混合架构**：

- **布局检测**交给专用 CV 模型（快、准、稳），负责定位和分类页面中的各区域，输出区域坐标与类型
- **内容识别**交给大参数量视觉 LLM（如 Qwen3.5-plus、GPT-4o 等），**以整页图片 + 区域坐标提示的方式**送入，让 VLM 在完整上下文中精准识别目标区域内容，追求极致精度
- **图片提取**由 CV 坐标定位后裁剪保存，保留原始图片质量
- **原生文本层**优先直接提取，VLM 作为校验/补充手段
- 各模块各司其职，通过标准化的中间数据格式解耦

### 1.3 目标用户场景

- **学术研究者**：将论文 PDF（扫描版或数字版）转为可编辑的 Markdown，便于引用与批注
- **文档数字化**：将历史扫描档案、报告转为结构化文本
- **RAG 数据准备**：为大模型知识库准备高质量文档数据
- **开发者集成**：通过 API 将 PDF 转换能力嵌入自有系统
- **产品体验**：通过 Demo 网站快速体验和评估转换效果

### 1.4 产品交付形式

ScanDoc2MD 提供以下三种使用方式：

| 形式 | 说明 |
|------|------|
| **Python SDK** | 核心库，支持同步/异步调用，可嵌入任意 Python 项目 |
| **API 服务** | 基于 FastAPI 的 HTTP API，提供完整的文档转换服务 |
| **Demo 网站** | 基于前端框架的可视化体验页面，用于项目测试与展示 |

### 1.5 与同类项目的差异

| 对比项 | MinerU | Zerox / gptpdf | ScanDoc2MD |
|--------|--------|----------------|------------|
| 布局检测 | 自带 DocLayout-YOLO | 无 | 可插拔 CV 模型 |
| OCR 引擎 | 自带小模型 / VLM | 全靠 VLM | 大参数 VLM（可配置） |
| 图片提取 | ✅ 支持 | ❌ 不支持 | ✅ 支持 |
| 扫描件支持 | ✅ | 有限（无图片提取） | ✅ 专门优化 |
| 原生 PDF 支持 | ✅ | 有限 | ✅ 文本层优先 + VLM 补充 |
| VLM 可替换 | 仅限自带模型 + llm-aided | 支持多 provider | 完全可插拔 |
| API 服务 | ❌ | ❌ | ✅ RESTful API |
| 在线 Demo | ❌ | ❌ | ✅ 可视化体验 |
| 部署复杂度 | 高（需要多个模型） | 低 | 中等 |

---

## 2. 系统架构

### 2.1 整体流程

```
输入: 任意 PDF 文档
  │
  ▼
[模块Z] PDF 类型检测器 (新增)
  │  逐页判断：是否有可用文本层
  │  输出: page_type = "scanned" | "native" | "mixed"
  ▼
  ┌──────────── 分支判断 ────────────┐
  │                                   │
  │ scanned / mixed 页面              │ native 页面（文本层完整且可信）
  ▼                                   ▼
[模块A] PDF 页面渲染器           [模块A'] 原生文本提取器
  │  渲染为高分辨率 PNG               │  直接提取文本、表格、图片
  ▼                                   ▼
[模块B] 布局检测引擎             (可选) 布局检测做 fallback
  │  区域检测 + 分类                  │
  ▼                                   │
[模块C] 区域处理器                    │
  │  整页+坐标送VLM / 图片裁剪保存    │
  ▼                                   │
  └──────────── 合并 ─────────────────┘
                  │
                  ▼
[模块F] Markdown 组装器
  │  按阅读顺序拼装所有识别结果
  ▼
输出: 结构化 Markdown 文件 + images/ 目录
```

### 2.2 扫描件/混合页面的详细流程

```
[模块A] PDF 页面渲染器
  │  将每页渲染为高分辨率 PNG 图片
  ▼
[模块B] 布局检测引擎
  │  对每页图片进行区域检测，输出各区域的:
  │  - 类型 (text / image / table / formula / title / header / footer)
  │  - 边界框坐标 (x1, y1, x2, y2)
  │  - 置信度分数
  │  - 阅读顺序编号
  ▼
[模块C] 区域处理器 (按类型分发)
  │  内容识别类: 整页图片 + 区域坐标 → VLM (更多上下文, 更高精度)
  │  图片类: 按坐标裁剪 → 保存为文件
  │
  ├── text 区域 ──→ [模块D] VLM (整页+坐标提示) ──→ 识别后的文本
  ├── title 区域 ──→ [模块D] VLM (整页+坐标提示) ──→ 标题文本 (带层级)
  ├── image 区域 ──→ [模块E] 图片保存器 (坐标裁剪) ──→ 独立图片文件
  ├── table 区域 ──→ [模块D] VLM (整页+坐标提示) ──→ Markdown/HTML 表格
  ├── formula 区域 ──→ [模块D] VLM (整页+坐标提示) ──→ LaTeX 公式
  └── header/footer ──→ 可选保留或丢弃
  │
  ▼
[模块F] Markdown 组装器
```

### 2.3 目录结构约定

```
output/
├── document.md           # 最终 Markdown 文件
├── images/               # 提取的图片
│   ├── page1_fig1.png
│   ├── page1_fig2.png
│   └── page3_table1.png  # 复杂表格也可以同时保存为图片备份
└── metadata.json         # 处理元数据（页数、区域统计、耗时、成本等）
```

---

## 3. 模块详细设计

### 3.1 模块Z：PDF 类型检测器（新增）

**职责**：逐页判断 PDF 的类型，决定后续处理策略。

**检测逻辑**：

```python
class PageType(Enum):
    SCANNED = "scanned"    # 纯扫描件页：无文本层 或 文本层为 OCR 垃圾
    NATIVE = "native"      # 原生数字页：有完整且可信的文本层
    MIXED = "mixed"        # 混合页：部分区域有文本层，部分是图片

@dataclass
class PageClassification:
    page_number: int
    page_type: PageType
    text_coverage: float       # 文本层覆盖率 (0-1)
    text_layer_quality: float  # 文本层质量分数 (0-1, 基于字符合理性判断)
    has_embedded_images: bool   # 是否包含嵌入图片
```

**判断策略**：

```
1. 提取页面文本层 → 如果文本层为空或字符数极少 → SCANNED
2. 对文本层进行质量检测（乱码率、字符分布合理性）→ 质量过低 → SCANNED
3. 检查页面是否包含大面积图片覆盖 → 如果有 → MIXED
4. 文本层完整且可信 → NATIVE
```

**配置项**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `force_mode` | str \| None | None | 强制指定模式：`"scanned"` / `"native"` / `None`自动 |
| `text_quality_threshold` | float | 0.7 | 文本层质量低于此值视为不可信 |
| `min_text_chars` | int | 20 | 页面文本层字符数低于此值视为无文本层 |

---

### 3.2 模块A：PDF 页面渲染器

**职责**：将 PDF 每页渲染为高分辨率位图（主要用于 scanned / mixed 页面）。

**技术选型**：`PyMuPDF (fitz)` 或 `pdf2image (poppler)`

**配置项**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `render_dpi` | int | 300 | 渲染分辨率。扫描件建议 300，追求极致可设 400 |
| `image_format` | str | "png" | 输出格式，png 无损 |
| `page_range` | list[int] \| None | None | 指定处理的页码范围，None 表示全部 |

**输出**：`list[PageImage]`

```python
@dataclass
class PageImage:
    page_number: int          # 页码 (从1开始)
    image: PIL.Image.Image    # 渲染后的页面图片
    width: int                # 图片宽度 (px)
    height: int               # 图片高度 (px)
```

**注意事项**：
- 需要自动检测并校正 EXIF 方向
- 对于原生 PDF 的 mixed 页面，也需渲染以便布局检测处理图片区域

---

### 3.3 模块A'：原生文本提取器（新增）

**职责**：对 `NATIVE` 类型的页面，直接从 PDF 文本层提取结构化内容。

**技术选型**：`PyMuPDF (fitz)` 的文本提取 API

**提取内容**：

```python
@dataclass
class NativePageContent:
    page_number: int
    text_blocks: list[TextBlock]       # 文本块（含位置信息）
    embedded_images: list[EmbeddedImage]  # 嵌入的图片对象
    tables: list[NativeTable] | None   # 如果 fitz 能提取表格结构

@dataclass
class TextBlock:
    text: str
    bbox: tuple[int, int, int, int]
    font_size: float
    font_name: str
    is_bold: bool
    is_italic: bool

@dataclass
class EmbeddedImage:
    image: PIL.Image.Image
    bbox: tuple[int, int, int, int]
    page_number: int
```

**处理逻辑**：
- 文本：直接提取，保留字体信息用于推断标题层级
- 嵌入图片：直接从 PDF 中提取图片对象（比渲染后裁剪质量更高）
- 表格：尝试用 PyMuPDF 提取，如效果不佳，回退到渲染 + VLM 方案
- 公式：原生 PDF 中的公式通常无法直接提取，仍需渲染 + VLM 识别

---

### 3.4 模块B：布局检测引擎

**职责**：对页面图片进行区域检测和分类。

**设计要求**：可插拔架构，通过适配器模式支持不同的布局检测后端。

**默认后端**：`DocLayout-YOLO`（MinerU 使用的同款模型，高精度布局检测）

**可选后端**（后续扩展）：
- YOLO 系列自训练模型
- VLM grounding（如 Qwen2.5-VL 的坐标输出能力）
- PaddleOCR 布局分析

**抽象接口**：

```python
class LayoutDetector(Protocol):
    def detect(self, image: PIL.Image.Image) -> list[LayoutBlock]:
        """对单页图片进行布局检测"""
        ...

@dataclass
class LayoutBlock:
    block_type: BlockType      # 区域类型枚举
    bbox: tuple[int, int, int, int]  # (x1, y1, x2, y2) 像素坐标
    confidence: float          # 检测置信度 0-1
    reading_order: int         # 阅读顺序编号
    page_number: int           # 所在页码

class BlockType(Enum):
    TITLE = "title"             # 标题
    TEXT = "text"               # 正文段落
    IMAGE = "image"             # 图片/插图/照片
    TABLE = "table"             # 表格
    FORMULA = "formula"         # 数学公式（行间公式）
    HEADER = "header"           # 页眉
    FOOTER = "footer"           # 页脚
    PAGE_NUMBER = "page_number" # 页码
    CAPTION = "caption"         # 图表标题/说明文字
    LIST = "list"               # 列表
    CODE = "code"               # 代码块
    REFERENCE = "reference"     # 参考文献区域
```

**配置项**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `confidence_threshold` | float | 0.5 | 低于此值的检测结果丢弃 |
| `merge_adjacent_text` | bool | True | 是否合并相邻的 text 区域 |
| `detect_reading_order` | bool | True | 是否进行阅读顺序排序 |
| `discard_types` | list[str] | ["header", "footer", "page_number"] | 默认丢弃的区域类型 |

---

### 3.5 模块C：区域处理分发器

**职责**：根据区域类型分发到不同的处理器。采用**"整页送 VLM + 坐标提示"**的策略，让 VLM 在完整页面上下文中识别指定区域，而非裁剪小图片送入。

**设计理念**：

CV 模型（模块B）已经精确定位了各区域的坐标和类型，模块C 的核心职责是：
- 对于**内容识别类**区域：将**整页图片 + 目标区域坐标**一起送给 VLM，让 VLM 拥有完整上下文来理解和识别
- 对于**图片类**区域：仅需按坐标裁剪保存像素，不需要 VLM 的"理解"能力

这样做的核心优势：
- VLM 能看到目标区域**周围的上下文**，避免因 bbox 略有偏差而截断内容
- 公式、表格等 bbox 容易切偏的区域，VLM 可自行判断实际边界，**精度显著提升**
- 跨区域关联（如表格标题与表格体相邻）也能被 VLM 自然感知
- 同一页面的多个相邻区域可**合并为一次 VLM 调用**，减少请求次数

**核心逻辑**：

```
对每个 LayoutBlock (按页分组):
    if block_type in [TITLE, TEXT, CAPTION, LIST, REFERENCE, CODE]:
        → 整页图片 + bbox 坐标 → 送 VLM OCR 引擎 → 识别文字
    elif block_type == IMAGE:
        → 按 bbox 坐标裁剪 → 保存为独立图片文件
        → (可选) 整页图片 + bbox → 送 VLM 生成图片描述作为 alt text
    elif block_type == TABLE:
        → 整页图片 + bbox 坐标 → 送 VLM 识别为 Markdown 表格或 HTML
        → 同时按 bbox 裁剪保存表格区域图片作为备份
    elif block_type == FORMULA:
        → 整页图片 + bbox 坐标 → 送 VLM 识别为 LaTeX
    elif block_type in discard_types:
        → 跳过
```

**同页区域合并策略**：

为减少 VLM 调用次数，同一页面内相邻的同类型区域可合并为一次请求，在 prompt 中列出多个坐标区域，让 VLM 一次性识别：

```python
def merge_blocks_for_vlm(blocks: list[LayoutBlock]) -> list[VLMRequest]:
    """将同页、相邻、同类型的区域合并为一次 VLM 请求"""
    requests = []
    # 按页分组
    for page_num, page_blocks in group_by_page(blocks):
        # 相邻同类型区域合并
        merged = merge_adjacent_same_type(page_blocks)
        for group in merged:
            requests.append(VLMRequest(
                page_image=get_page_image(page_num),
                target_regions=[(b.bbox, b.block_type) for b in group],
                block_type=group[0].block_type
            ))
    return requests
```

**图片区域裁剪时的边距处理**：

仅对需要保存为文件的图片区域进行裁剪，裁剪时在 bbox 基础上向外扩展少量 padding，避免内容紧贴边界。

```python
def crop_with_padding(image: PIL.Image.Image, bbox: tuple, padding: int = 8) -> PIL.Image.Image:
    x1, y1, x2, y2 = bbox
    x1 = max(0, x1 - padding)
    y1 = max(0, y1 - padding)
    x2 = min(image.width, x2 + padding)
    y2 = min(image.height, y2 + padding)
    return image.crop((x1, y1, x2, y2))
```

---

### 3.6 模块D：VLM OCR 引擎

**职责**：调用大参数量视觉 LLM 对页面中的指定区域进行高精度内容识别。VLM 接收**整页图片 + 目标区域坐标**，在完整上下文中精准识别。

**设计要求**：
- 通过 OpenAI 兼容 API 接口统一接入，支持任意 VLM provider
- 接收整页图片和区域坐标，在 prompt 中指示 VLM 聚焦目标区域
- 不同区域类型使用不同的 system prompt
- 支持同页多区域合并为一次请求
- 支持并发请求以提升吞吐
- 支持重试和错误处理

**抽象接口**：

```python
class VLMEngine(Protocol):
    async def recognize(
        self,
        page_image: PIL.Image.Image,     # 整页图片
        target_bbox: tuple[int, int, int, int],  # 目标区域坐标 (x1, y1, x2, y2)
        block_type: BlockType,
        context: str | None = None       # 可选的上下文信息
    ) -> RecognitionResult:
        ...

    async def recognize_batch(
        self,
        page_image: PIL.Image.Image,     # 整页图片
        targets: list[tuple[tuple[int, int, int, int], BlockType]],  # 多个区域
        context: str | None = None
    ) -> list[RecognitionResult]:
        """同一页面多区域批量识别，减少 API 调用次数"""
        ...

@dataclass
class RecognitionResult:
    content: str               # 识别出的文本/LaTeX/Markdown表格
    content_type: str          # "text" | "latex" | "markdown_table" | "html_table"
    confidence: float | None   # 模型自评置信度（如果模型支持）
    target_bbox: tuple[int, int, int, int]  # 对应的目标区域坐标
    raw_response: str          # 原始模型输出（用于调试）
```

**各区域类型的 Prompt 策略**：

```yaml
text_prompt: |
  你是一个专业的 OCR 系统。图片是一个完整的文档页面。
  请精确识别坐标区域 ({x1}, {y1}) 到 ({x2}, {y2}) 范围内的所有文字内容。
  坐标以像素为单位，左上角为原点。
  要求：
  - 只识别指定坐标区域内的文字，忽略区域外的内容
  - 逐字精确，不要遗漏或添加任何内容
  - 保留原文的段落结构
  - 如果有加粗、斜体等格式，用 Markdown 语法标记
  - 不要输出任何解释性文字，只输出识别结果

title_prompt: |
  请识别图片中坐标区域 ({x1}, {y1}) 到 ({x2}, {y2}) 范围内的标题文字。
  只输出标题文本，不添加任何其他内容。

table_prompt: |
  请将图片中坐标区域 ({x1}, {y1}) 到 ({x2}, {y2}) 范围内的表格精确转换为 Markdown 表格格式。
  坐标以像素为单位，左上角为原点。
  要求：
  - 只关注指定坐标区域内的表格
  - 表头用 | --- | 分隔
  - 保持行列结构完全一致
  - 单元格内容精确识别
  - 如果表格过于复杂无法用 Markdown 表示，请使用 HTML <table> 标签
  - 不要输出任何解释性文字

formula_prompt: |
  请将图片中坐标区域 ({x1}, {y1}) 到 ({x2}, {y2}) 范围内的数学公式转换为 LaTeX 格式。
  坐标以像素为单位，左上角为原点。
  要求：
  - 只关注指定坐标区域内的公式
  - 用 $$ $$ 包裹行间公式
  - 精确还原所有数学符号、上下标、分数、积分等
  - 不要输出任何解释性文字，只输出 LaTeX 代码

caption_prompt: |
  请识别图片中坐标区域 ({x1}, {y1}) 到 ({x2}, {y2}) 范围内的说明文字（图标题或表标题）。
  只输出文本内容。

image_alt_prompt: |
  请观察图片中坐标区域 ({x1}, {y1}) 到 ({x2}, {y2}) 范围内的图片内容，
  用一句简洁的中文描述，用于 Markdown 的 alt text。不要超过 50 个字。

batch_prompt: |
  你是一个专业的 OCR 系统。图片是一个完整的文档页面。
  请依次识别以下各坐标区域的内容，每个区域的结果用 [REGION_N] 标记分隔：
  {regions_description}
  要求：
  - 对每个区域，只识别该坐标范围内的内容
  - 逐字精确，保留格式
  - 用 [REGION_1], [REGION_2], ... 标记各区域结果的开头
```

**配置项**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `api_base_url` | str | — | OpenAI 兼容 API 地址 |
| `api_key` | str | — | API 密钥 |
| `model` | str | "qwen-vl-max" | 模型名称 |
| `max_concurrent` | int | 5 | 最大并发请求数 |
| `timeout` | int | 60 | 单次请求超时秒数 |
| `max_retries` | int | 3 | 失败重试次数 |
| `temperature` | float | 0.1 | 生成温度，OCR 任务建议极低 |
| `recognition_mode` | str | "full_page" | 识别模式：`full_page`（整页+坐标, 推荐）/ `crop`（裁剪小图送入, 兼容模式） |
| `batch_regions` | bool | True | 是否将同页相邻区域合并为一次 VLM 请求 |
| `max_regions_per_batch` | int | 5 | 单次批量请求最多包含的区域数 |
| `generate_image_alt` | bool | True | 是否为提取的图片生成 alt 描述 |
| `custom_prompts` | dict | {} | 自定义各类型的 prompt，覆盖默认 |
| `document_context` | str | "" | 文档整体上下文描述，附加到每次请求中以提高识别准确性 |

**Provider 预设**（方便用户快速配置）：

```yaml
providers:
  dashscope:
    api_base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model: "qwen-vl-max"  # 或 qwen3.5-plus-latest 等
  openai:
    api_base_url: "https://api.openai.com/v1"
    model: "gpt-4o"
  gemini:
    api_base_url: "https://generativelanguage.googleapis.com/v1beta/openai/"
    model: "gemini-2.5-pro"
  local_ollama:
    api_base_url: "http://localhost:11434/v1"
    model: "qwen3-vl:32b"
```

---

### 3.7 模块E：图片保存器

**职责**：将检测为 image 类型的区域按坐标从页面图片中裁剪出来，保存为独立文件。这是唯一需要对页面图片进行坐标裁剪的模块（内容识别类区域走整页+坐标送 VLM 路径，不裁剪）。

**命名规则**：`page{页码}_fig{序号}.png`，如 `page1_fig1.png`、`page3_fig2.png`

**处理逻辑**：

```python
def extract_image(
    page_image: PIL.Image.Image,
    block: LayoutBlock,
    output_dir: Path,
    padding: int = 5
) -> ImageReference:
    """裁剪并保存图片，返回引用信息"""
    cropped = crop_with_padding(page_image, block.bbox, padding)

    # 生成文件名
    filename = f"page{block.page_number}_fig{fig_counter}.png"
    filepath = output_dir / "images" / filename
    cropped.save(filepath, "PNG")

    return ImageReference(
        filename=filename,
        relative_path=f"images/{filename}",
        width=cropped.width,
        height=cropped.height,
        page_number=block.page_number,
        reading_order=block.reading_order
    )
```

**原生 PDF 图片提取**：对于 `NATIVE` 页面，优先直接从 PDF 中提取嵌入图片对象（质量更高，无渲染损失），而非从渲染图中裁剪。

**注意**：本模块仅负责 image 类型区域的像素级裁剪保存。text / table / formula 等内容识别类区域**不经过本模块**，而是由模块C将整页图片+坐标直接送给模块D (VLM) 处理。

**配置项**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `image_format` | str | "png" | 保存格式 |
| `image_quality` | int | 95 | JPEG 质量（仅 jpg 格式时生效） |
| `min_image_size` | int | 50 | 宽或高小于此值(px)的图片区域忽略（可能是噪点） |
| `padding` | int | 5 | 裁剪时的外扩像素数 |
| `save_table_images` | bool | True | 是否同时将表格区域保存为图片备份 |
| `prefer_embedded` | bool | True | 原生 PDF 优先提取嵌入图片而非裁剪 |

---

### 3.8 模块F：Markdown 组装器

**职责**：按阅读顺序将所有处理结果拼装为最终 Markdown 文件。

**组装规则**：

```
1. 按 page_number 排序，同页内按 reading_order 排序
2. 页与页之间插入分页标记（可配置）
3. 合并来自 scanned 路径和 native 路径的结果
4. 不同类型的内容使用不同的 Markdown 语法：
   - TITLE → # / ## / ### (根据字号或位置推断层级)
   - TEXT → 直接输出段落文本，段落间空行分隔
   - IMAGE → ![alt_text](images/pageX_figY.png)
   - TABLE → 直接嵌入 Markdown/HTML 表格
   - FORMULA → $$ LaTeX $$ 块
   - CAPTION → 紧跟在关联的 image/table 之后，用 *斜体* 标记
   - LIST → 保留列表格式
   - CODE → ``` 代码块 ```
   - REFERENCE → 放在文档末尾的参考文献区
```

**配置项**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `page_separator` | str | "\n\n---\n\n" | 页间分隔符 |
| `include_page_markers` | bool | False | 是否插入 `<!-- Page X -->` 标记 |
| `image_ref_style` | str | "relative" | 图片引用方式：relative / absolute / base64_inline |
| `title_level_strategy` | str | "auto" | 标题层级推断策略：auto / flat / positional |
| `discard_header_footer` | bool | True | 是否丢弃页眉页脚内容 |

---

## 4. API 服务设计（新增）

### 4.1 技术选型

- **框架**：FastAPI（高性能异步框架，自动生成 OpenAPI 文档）
- **任务队列**：后台任务使用 FastAPI BackgroundTasks，大规模场景可选 Celery + Redis
- **文件存储**：本地磁盘，支持配置 S3 等对象存储（后续扩展）

### 4.2 API 端点设计

#### 4.2.1 文档转换

```
POST /api/v1/convert
```

**请求**：`multipart/form-data`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | File | ✅ | PDF 文件 |
| `config` | JSON string | ❌ | 覆盖默认转换配置（同 config.yaml 中的字段） |
| `page_range` | string | ❌ | 页码范围，如 `"1-5,8,10"` |
| `callback_url` | string | ❌ | 转换完成后的回调 URL |

**响应**（同步模式，小文件）：

```json
{
  "task_id": "uuid-xxxx",
  "status": "completed",
  "result": {
    "markdown": "## Title\n\nContent...",
    "images": [
      {
        "filename": "page1_fig1.png",
        "url": "/api/v1/files/{task_id}/images/page1_fig1.png",
        "width": 640,
        "height": 480
      }
    ],
    "metadata": {
      "total_pages": 12,
      "processing_time_seconds": 45.2,
      "api_calls": 89,
      "page_types": {"scanned": 8, "native": 4}
    }
  }
}
```

**响应**（异步模式，大文件）：

```json
{
  "task_id": "uuid-xxxx",
  "status": "processing",
  "progress_url": "/api/v1/tasks/{task_id}"
}
```

#### 4.2.2 任务状态查询

```
GET /api/v1/tasks/{task_id}
```

**响应**：

```json
{
  "task_id": "uuid-xxxx",
  "status": "processing",  // "queued" | "processing" | "completed" | "failed"
  "progress": {
    "current_page": 5,
    "total_pages": 12,
    "percent": 41.7
  },
  "created_at": "2026-03-22T10:00:00Z",
  "updated_at": "2026-03-22T10:00:23Z"
}
```

#### 4.2.3 获取转换结果

```
GET /api/v1/tasks/{task_id}/result
```

返回完整的转换结果（Markdown + 元数据）。

#### 4.2.4 下载结果文件

```
GET /api/v1/files/{task_id}/document.md
GET /api/v1/files/{task_id}/images/{filename}
GET /api/v1/files/{task_id}/result.zip       # 打包下载所有文件
```

#### 4.2.5 健康检查

```
GET /api/v1/health
```

```json
{
  "status": "ok",
  "version": "0.1.0",
  "layout_engine": "doclayout-yolo",
  "vlm_provider": "dashscope",
  "vlm_model": "qwen-vl-max"
}
```

### 4.3 API 配置项

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `host` | str | "0.0.0.0" | 监听地址 |
| `port` | int | 8000 | 监听端口 |
| `max_file_size_mb` | int | 100 | 上传文件大小上限 |
| `max_pages` | int | 200 | 单次转换最大页数 |
| `async_threshold_pages` | int | 10 | 超过此页数自动切换异步模式 |
| `task_ttl_hours` | int | 24 | 任务结果保留时长 |
| `cors_origins` | list[str] | ["*"] | CORS 允许的来源（生产环境应限制） |
| `rate_limit` | str | "10/minute" | 速率限制 |

### 4.4 认证与安全

- **API Key 认证**：通过 `Authorization: Bearer <api_key>` 请求头传递
- **速率限制**：基于 IP 或 API Key 的请求频率限制
- **文件校验**：校验上传文件的 MIME 类型与大小
- **CORS**：默认开放（开发模式），生产环境需配置允许的来源
- **输入清洗**：防止路径遍历等安全问题

---

## 5. Demo 网站设计（新增）

### 5.1 定位

提供一个简洁的可视化前端，用于：

- 快速体验 ScanDoc2MD 的转换效果
- 方便项目演示和测试
- 作为 API 集成的参考实现

### 5.2 技术选型

| 组件 | 推荐方案 | 备选方案 |
|------|----------|----------|
| 前端框架 | Vue 3 + Vite | React |
| UI 组件库 | Element Plus / Naive UI | Ant Design Vue |
| Markdown 渲染 | markdown-it + highlight.js | |
| HTTP 客户端 | axios | |
| 部署 | Nginx 静态部署 + API 反向代理 | Docker Compose 一体化 |

### 5.3 页面功能

#### 5.3.1 主页面（单页应用）

```
┌───────────────────────────────────────────────────┐
│  ScanDoc2MD                           [设置] [关于]  │
├───────────────────────────────────────────────────┤
│                                                     │
│  ┌─────────────────────────────────────────────┐   │
│  │                                               │   │
│  │     拖拽上传 PDF 文件                          │   │
│  │     或 点击选择文件                            │   │
│  │                                               │   │
│  │     支持: 扫描件 / 原生 / 混合 PDF            │   │
│  │     限制: ≤ 100MB, ≤ 200 页                   │   │
│  │                                               │   │
│  └─────────────────────────────────────────────┘   │
│                                                     │
│  ── 转换选项（可折叠） ──                           │
│  VLM 模型: [qwen-vl-max ▾]   DPI: [300 ▾]         │
│  页码范围: [全部________]                            │
│                                                     │
│  [开始转换]                                         │
│                                                     │
├───────────────────────────────────────────────────┤
│  ── 转换进度 ──                                     │
│  ████████░░░░░░░░ 42% (5/12 页)                    │
│  当前: 正在识别 Page 5 的表格区域...                 │
│                                                     │
├───────────────────────────────────────────────────┤
│  ── 转换结果（双栏对比） ──                         │
│                                                     │
│  ┌──────────────┐  ┌──────────────────────────┐    │
│  │ PDF 原始预览  │  │ Markdown 渲染预览         │    │
│  │              │  │                          │    │
│  │  (PDF 页面)  │  │  (渲染后的 Markdown)      │    │
│  │              │  │                          │    │
│  └──────────────┘  └──────────────────────────┘    │
│                                                     │
│  [复制 Markdown]  [下载 .md]  [下载 .zip]           │
│                                                     │
└───────────────────────────────────────────────────┘
```

#### 5.3.2 核心功能点

| 功能 | 说明 |
|------|------|
| PDF 上传 | 拖拽或点击上传，显示文件基本信息（页数、大小） |
| 转换选项 | 选择模型、DPI、页码范围等常用参数 |
| 实时进度 | 轮询 API 任务状态，显示进度条与当前处理步骤 |
| PDF 预览 | 左侧展示原始 PDF 页面（可翻页） |
| Markdown 预览 | 右侧渲染 Markdown 结果，支持图片显示与 LaTeX 渲染 |
| 源码查看 | 可切换为查看原始 Markdown 源码 |
| 结果下载 | 支持复制 Markdown、下载 `.md` 文件、下载包含图片的 `.zip` 压缩包 |

### 5.4 设置面板

| 设置项 | 说明 |
|--------|------|
| API 地址 | 默认指向本地 `http://localhost:8000`，支持自定义 |
| API Key | 可选填入 API Key |
| VLM Provider | 选择预设 provider 或自定义 |
| 模型 | 模型名称 |
| 渲染 DPI | 渲染分辨率 |
| 主题 | 亮色 / 暗色模式 |

---

## 6. 配置系统设计

### 6.1 统一配置文件

使用单一 YAML 文件 `config.yaml` 管理所有配置：

```yaml
# scandoc2md 配置文件

# 全局设置
general:
  render_dpi: 300
  page_range: null          # null 表示处理所有页, 或 [1, 2, 5] 指定页码
  output_dir: "./output"
  document_context: ""      # 可填写如 "这是一篇关于深度学习的学术论文"

# PDF 类型检测 (新增)
pdf_detection:
  force_mode: null          # null (自动), "scanned", "native"
  text_quality_threshold: 0.7
  min_text_chars: 20

# 布局检测
layout:
  engine: "doclayout-yolo"  # 可选: doclayout-yolo, vlm-grounding, paddleocr
  confidence_threshold: 0.5
  merge_adjacent_text: true
  discard_types:
    - header
    - footer
    - page_number

# VLM OCR
vlm:
  provider: "dashscope"     # 预设 provider 名, 或自定义下方字段
  api_base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  api_key: "${SCANDOC_API_KEY}"   # 支持环境变量引用
  model: "qwen-vl-max"
  temperature: 0.1
  max_concurrent: 5
  max_retries: 3
  timeout: 60
  recognition_mode: "full_page"  # "full_page"(整页+坐标) 或 "crop"(裁剪小图)
  batch_regions: true       # 同页区域合并为一次请求
  max_regions_per_batch: 5  # 单次批量请求最多区域数
  generate_image_alt: true
  custom_prompts: {}        # 可覆盖默认 prompt

# 图片提取
image_extraction:
  format: "png"
  min_size: 50
  padding: 5
  save_table_images: true
  prefer_embedded: true     # 原生 PDF 优先提取嵌入图片 (新增)

# Markdown 输出
markdown:
  page_separator: "\n\n---\n\n"
  include_page_markers: false
  image_ref_style: "relative"
  title_level_strategy: "auto"

# API 服务 (新增)
api:
  host: "0.0.0.0"
  port: 8000
  max_file_size_mb: 100
  max_pages: 200
  async_threshold_pages: 10
  task_ttl_hours: 24
  cors_origins: ["*"]
  rate_limit: "10/minute"
  api_keys: []              # 生产环境配置允许的 API Key 列表, 空列表表示不启用认证
```

### 6.2 环境变量

| 环境变量 | 说明 |
|----------|------|
| `SCANDOC_API_KEY` | VLM API 密钥 |
| `SCANDOC_CONFIG` | 配置文件路径（默认 `./config.yaml`） |
| `SCANDOC_SERVER_HOST` | API 服务监听地址（覆盖配置文件） |
| `SCANDOC_SERVER_PORT` | API 服务监听端口（覆盖配置文件） |

---

## 7. CLI 接口设计

### 7.1 基本用法

```bash
# 最简用法 — 转换单个 PDF
scandoc2md convert input.pdf -o output/

# 指定配置文件
scandoc2md convert input.pdf -o output/ --config my_config.yaml

# 命令行覆盖参数
scandoc2md convert input.pdf -o output/ \
  --model qwen-vl-max \
  --api-key sk-xxx \
  --dpi 400 \
  --pages 1,2,3,5-10

# 强制指定 PDF 处理模式
scandoc2md convert input.pdf -o output/ --force-mode scanned

# 批量处理目录下所有 PDF
scandoc2md convert ./pdfs/ -o output/ --batch

# 仅做布局检测（调试用，不调用 VLM）
scandoc2md convert input.pdf -o output/ --layout-only

# 仅处理指定类型的区域
scandoc2md convert input.pdf -o output/ --only-types text,table,image
```

### 7.2 启动 API 服务

```bash
# 启动 API 服务
scandoc2md serve

# 指定端口
scandoc2md serve --port 9000

# 使用自定义配置
scandoc2md serve --config production.yaml
```

### 7.3 输出示例

```
Processing: input.pdf
  Detecting PDF types...
  Page types: 8 scanned, 4 native

  [1/12] Page 1 (scanned): 8 blocks detected (3 text, 2 image, 1 table, 1 title, 1 caption)
  [2/12] Page 2 (scanned): 5 blocks detected (4 text, 1 formula)
  ...
  [9/12] Page 9 (native): text extracted directly, 2 embedded images
  ...
  [12/12] Page 12 (scanned): 6 blocks detected (3 text, 2 reference, 1 footer)

Results:
  Output:     output/document.md
  Images:     output/images/ (7 files)
  Total time: 45.2s
  API calls:  65 (saved 24 calls via native text extraction)
  Est. cost:  ¥0.32

Done.
```

---

## 8. Python SDK 接口设计

### 8.1 主入口

```python
from scandoc2md import ScanDoc2MD

converter = ScanDoc2MD(
    config_path="config.yaml"  # 或直接传 dict
)

# 同步接口
result = converter.convert("input.pdf", output_dir="./output")
print(result.markdown)          # Markdown 文本
print(result.images)            # 提取的图片列表
print(result.metadata)          # 处理元数据
print(result.metadata.page_types)  # 各页类型信息

# 异步接口
result = await converter.aconvert("input.pdf", output_dir="./output")
```

### 8.2 逐模块调用（高级用法）

```python
from scandoc2md import PDFRenderer, PDFTypeDetector, LayoutDetector, VLMEngine, MarkdownAssembler

# Step 0: 类型检测
detector = PDFTypeDetector()
page_types = detector.classify("input.pdf")

# Step 1: 渲染 (仅 scanned/mixed 页面)
renderer = PDFRenderer(dpi=300)
pages = renderer.render("input.pdf", page_filter=lambda p: page_types[p].page_type != PageType.NATIVE)

# Step 1': 原生提取 (仅 native 页面)
native_content = renderer.extract_native("input.pdf", page_filter=lambda p: page_types[p].page_type == PageType.NATIVE)

# Step 2: 布局检测 (仅渲染页面)
layout = LayoutDetector(engine="doclayout-yolo")
all_blocks = []
for page in pages:
    blocks = layout.detect(page.image)
    all_blocks.extend(blocks)

# Step 3: VLM 识别 + 图片提取
vlm = VLMEngine(provider="dashscope", model="qwen-vl-max")
processed = await vlm.process_blocks(all_blocks, pages)

# Step 4: 合并 + 组装
assembler = MarkdownAssembler()
markdown = assembler.assemble(processed, native_content, output_dir="./output")
```

---

## 9. 技术栈

### 9.1 核心依赖

| 组件 | 推荐库 | 用途 |
|------|--------|------|
| PDF 渲染 | `PyMuPDF (fitz)` | PDF 页面转图片 + 原生文本提取 |
| 布局检测 | `DocLayout-YOLO` / `ultralytics` | 区域检测和分类 |
| 图片处理 | `Pillow` | 裁剪、保存、格式转换 |
| VLM 调用 | `httpx` (async) 或 `openai` SDK | 异步 HTTP 请求 |
| 配置管理 | `pydantic` + `PyYAML` | 配置校验和加载 |
| CLI | `typer` 或 `click` | 命令行接口 |
| 进度显示 | `rich` | 进度条和美化输出 |
| 并发控制 | `asyncio` + `asyncio.Semaphore` | 控制 VLM 并发数 |
| **API 框架** | `FastAPI` + `uvicorn` | HTTP API 服务 |
| **任务管理** | `FastAPI BackgroundTasks` | 异步任务处理 |
| **前端框架** | `Vue 3` + `Vite` | Demo 网站 |
| **UI 组件** | `Element Plus` / `Naive UI` | 前端 UI 组件 |
| **Markdown 渲染** | `markdown-it` | 前端 Markdown 渲染 |

### 9.2 开发环境

- Python >= 3.10
- Node.js >= 18（Demo 前端）
- 包管理：`uv` 或 `pip`（Python），`pnpm` 或 `npm`（前端）
- 格式化：`ruff`（Python），`eslint` + `prettier`（前端）
- 类型检查：`pyright` 或 `mypy`

---

## 10. 关键设计决策与权衡

### 10.1 为什么不让 VLM 做布局检测？

虽然大模型（如 Qwen3-VL）支持 grounding 输出坐标，但：

- **精度**：专用 YOLO 模型在布局检测上的 mAP 达 97.5%，VLM grounding 远不及
- **成本**：每页都调用大模型做布局检测太贵
- **速度**：YOLO 毫秒级，VLM 秒级
- **确定性**：CV 模型输出稳定，VLM 可能每次结果不同

结论：布局检测给 CV 模型，内容理解给 VLM。

### 10.2 为什么送整页图片+坐标而不是裁剪小图？

**核心选择：VLM 始终接收整页图片 + 坐标提示，而非裁剪后的区域小图。**

优势：
- **上下文完整**：VLM 能看到目标区域周围的内容，不会因 bbox 略有偏差而截断文字
- **精度更高**：公式、表格等 bbox 容易切偏的区域，VLM 可自行判断实际边界
- **跨区域关联**：相邻的 caption 和 image、表格标题和表格体等关系可被自然感知
- **容错更好**：即使 CV 模型的 bbox 有几个像素的偏移，VLM 依然能识别完整内容

代价与缓解：
- 每次请求传输整页图片 → token 消耗更大 → 通过**同页区域批量合并**为一次请求来缓解
- 整页图片分辨率需要足够高（300 DPI）以确保小区域也清晰可辨

**兼容模式**：提供 `recognition_mode: "crop"` 配置项，可回退到裁剪小图送 VLM 的传统模式（适用于 token 成本敏感或 VLM 不支持坐标指令的场景）。

### 10.3 同页区域批量识别

为减少 API 调用次数，同一页面的多个区域（尤其是同类型的）可合并为一次 VLM 请求，在 prompt 中列出多个坐标区域让 VLM 依次识别。判断条件：

```python
# 同页多区域合并为一次请求
page_blocks = group_by_page(blocks)
for page_num, page_block_list in page_blocks:
    if should_batch(page_block_list):  # 同类型或相邻区域
        results = await vlm.recognize_batch(
            page_image, 
            [(b.bbox, b.block_type) for b in page_block_list]
        )
    else:
        # 逐区域单独请求
        for block in page_block_list:
            result = await vlm.recognize(page_image, block.bbox, block.block_type)
```

对于布局极其简单的页面（如只有一块纯文字），可以不指定坐标，直接让 VLM 识别整页内容，进一步简化 prompt。

### 10.4 图片描述的 alt text 策略

提取的图片需要 alt text，有两种策略：

- **VLM 生成描述**：额外调用 VLM 对裁剪出的图片生成简短描述 → 效果好但多一次 API 调用
- **使用相邻 caption**：如果布局检测到了 caption 区域，且与 image 区域相邻，直接用 caption 文本作为 alt text → 零额外成本

推荐：**优先使用 caption，无 caption 时再调用 VLM 生成。**

### 10.5 原生 PDF vs 扫描件的策略选择（新增）

对于有完整文本层的原生 PDF 页面：

- **直接提取文本层**：速度快、成本零、精度高（原文就是文本）
- **仍需 VLM 的场景**：公式无法直接提取、复杂表格结构不完整、图片需要 alt text
- **混合页面**：文本区域直接提取，图片/表格/公式区域走 CV + VLM 路径

这一策略可以**显著降低原生/混合 PDF 的处理成本和耗时**。

---

## 11. 错误处理与鲁棒性

### 11.1 VLM 调用失败

- 单次超时 → 自动重试（最多 max_retries 次）
- 连续失败 → 记录到 metadata.json 中的 errors 字段，跳过该区域，在 Markdown 中插入占位符 `[OCR_FAILED: page X, block Y]`
- 速率限制 → 指数退避重试

### 11.2 布局检测异常

- 某页检测不到任何区域 → 回退到整页送 VLM
- 区域严重重叠 → NMS (非极大抑制) 去重
- 区域超出页面边界 → 裁剪到页面边界内

### 11.3 输入校验

- 非 PDF 文件 → 报错提示
- 空白页 → 跳过，日志记录
- 加密 PDF → 报错提示需要先解密
- 超大文件 (>1000页) → 警告并建议分批处理

### 11.4 API 服务错误处理（新增）

- 上传文件过大 → `413 Payload Too Large`
- 文件类型不合法 → `415 Unsupported Media Type`
- 任务不存在 → `404 Not Found`
- 服务内部错误 → `500 Internal Server Error`，附带错误追踪 ID
- 速率限制超出 → `429 Too Many Requests`

所有 API 错误返回统一格式：

```json
{
  "error": {
    "code": "FILE_TOO_LARGE",
    "message": "上传文件大小超过限制 (100MB)",
    "detail": null
  }
}
```

---

## 12. 性能优化

### 12.1 并发策略

```
PDF 渲染: 同步顺序处理（IO密集但很快）
原生文本提取: 同步顺序处理（极快）
布局检测: 可并行（如果 GPU 显存够）
VLM 调用: asyncio 并发，受 max_concurrent 限制
图片保存: 异步写盘
```

### 12.2 成本控制

- 原生页面直接提取文本：**零 VLM 调用成本**
- 同页区域批量合并：同一页面多个区域合并为一次 VLM 请求（整页图片 + 多个坐标），大幅减少调用次数（见 10.3）
- 简单页面整页识别：不指定坐标，直接让 VLM 识别整页
- token 估算：根据区域面积预估 token 消耗，在处理前给出成本预估
- dry-run 模式：`--dry-run` 只做类型检测 + 布局检测和成本预估，不调用 VLM

---

## 13. 部署方案（新增）

### 13.1 开发环境

```bash
# 后端
cd backend
uv sync
scandoc2md serve --port 8000

# 前端
cd frontend
pnpm install
pnpm dev   # 开发服务器默认 http://localhost:5173, 代理 API 到 8000
```

### 13.2 Docker 部署

```yaml
# docker-compose.yml
version: "3.8"
services:
  api:
    build: ./backend
    ports:
      - "8000:8000"
    volumes:
      - ./config.yaml:/app/config.yaml
      - ./data:/app/data
    environment:
      - SCANDOC_API_KEY=${SCANDOC_API_KEY}

  web:
    build: ./frontend
    ports:
      - "80:80"
    depends_on:
      - api
```

### 13.3 项目目录结构

```
scandoc2md/
├── backend/                    # Python 后端
│   ├── src/
│   │   └── scandoc2md/
│   │       ├── __init__.py
│   │       ├── core/           # 核心转换逻辑
│   │       │   ├── pdf_detector.py    # 模块Z: PDF 类型检测
│   │       │   ├── renderer.py        # 模块A: PDF 渲染器
│   │       │   ├── native_extractor.py # 模块A': 原生文本提取
│   │       │   ├── layout.py          # 模块B: 布局检测
│   │       │   ├── dispatcher.py      # 模块C: 区域分发器
│   │       │   ├── vlm.py             # 模块D: VLM 引擎
│   │       │   ├── image_saver.py     # 模块E: 图片保存器
│   │       │   └── assembler.py       # 模块F: Markdown 组装器
│   │       ├── api/            # FastAPI 服务
│   │       │   ├── app.py
│   │       │   ├── routes/
│   │       │   └── deps.py
│   │       ├── cli.py          # CLI 入口
│   │       ├── config.py       # 配置管理
│   │       └── models.py       # 数据模型
│   ├── tests/
│   ├── pyproject.toml
│   └── Dockerfile
├── frontend/                   # Vue 前端
│   ├── src/
│   │   ├── App.vue
│   │   ├── views/
│   │   ├── components/
│   │   └── api/
│   ├── package.json
│   └── Dockerfile
├── docs/
│   ├── requirements-v1.md
│   └── requirements-v2.md
├── config.yaml                 # 默认配置
├── docker-compose.yml
└── README.md
```

---

## 14. 后续扩展方向（非 MVP 范围）

以下功能不在首版实现范围内，但架构设计时需要预留扩展点：

1. **MCP Server 集成**：将 ScanDoc2MD 封装为 MCP 工具，供 Claude Code 等 AI agent 调用
2. **批量处理队列**：引入 Celery + Redis，支持大规模文档处理任务队列
3. **多模型 ensemble**：同一区域用多个 VLM 识别后投票/对比取最佳
4. **增量处理**：对已处理过的 PDF 只重新处理修改/新增页面
5. **原生 PDF 文本层校验**：对有文本层的 PDF，用 VLM OCR 结果与文本层对比，自动修正乱码
6. **自定义布局检测模型训练**：提供 fine-tuning 接口，用户可在自己的文档类型上训练布局模型
7. **用户系统**：多用户、配额管理、历史记录
8. **对象存储**：结果文件存储到 S3 / MinIO 等

---

## 15. 验收标准

### 15.1 功能验收

- [ ] 能正确处理纯扫描件 PDF（每页一张大图，无文本层）
- [ ] 能正确处理原生数字 PDF（自动提取文本层，减少 VLM 调用）
- [ ] 能正确处理混合型 PDF（逐页自适应选择处理策略）
- [ ] 能正确处理学术论文 PDF（双栏布局、公式、表格、引用）
- [ ] 布局检测能区分 text / image / table / formula / title 类型
- [ ] 文字区域通过 VLM 识别，输出准确的文本
- [ ] 图片区域被裁剪并保存为独立文件，Markdown 中有正确的引用路径
- [ ] 表格区域被识别为 Markdown/HTML 表格
- [ ] 公式区域被识别为 LaTeX
- [ ] 最终输出的 Markdown 文件结构合理、可读
- [ ] 支持通过配置文件切换不同的 VLM provider
- [ ] CLI 可用（convert / serve 命令）
- [ ] Python SDK 可用
- [ ] API 服务可正常启动并处理请求
- [ ] Demo 网站可上传 PDF、查看进度、预览并下载结果

### 15.2 测试用例

| 用例 | 输入 | 预期输出 |
|------|------|----------|
| 纯文字扫描件 | 只有段落文字的扫描 PDF | 干净的 Markdown 文本 |
| 原生数字 PDF | 有完整文本层的 PDF | 直接提取文本，VLM 调用数为 0 或极少 |
| 图文混排 | 含照片和说明文字的 PDF | 文字被识别 + 图片被提取保存 |
| 学术论文 | 含公式、表格、引用的论文 PDF | LaTeX 公式 + Markdown 表格 + 参考文献 |
| 多栏布局 | 双栏排版的论文 PDF | 正确的阅读顺序，不混淆左右栏 |
| 低质量扫描 | 模糊/倾斜的扫描件 | 尽力识别 + 错误区域有 fallback 标记 |
| 混合型 PDF | 部分页扫描、部分页原生 | 自适应策略，分别处理 |
| API 转换 | 通过 API 上传 PDF | 返回正确的 task_id + 最终结果 |
| Demo 网站 | 在网页上传并转换 | 进度展示正常，结果预览正确 |

---

## 附录 A：示例输出

### 输入：一页包含标题、正文、图片、表格的学术论文扫描件

### 期望输出 `document.md`：

```markdown
## 3. Experimental Results

We conducted extensive experiments on three benchmark datasets to evaluate
the performance of our proposed method. Table 1 summarizes the key metrics
across all baselines.

| Method | Precision | Recall | F1-Score |
|--------|-----------|--------|----------|
| Baseline A | 0.82 | 0.79 | 0.80 |
| Baseline B | 0.85 | 0.83 | 0.84 |
| **Ours** | **0.91** | **0.89** | **0.90** |

*Table 1: Comparison of methods on the benchmark dataset.*

As shown in Figure 5, our method achieves significantly better segmentation
quality, especially in boundary regions.

![Segmentation comparison between methods](images/page3_fig1.png)

*Figure 5: Visual comparison of segmentation results.*

The improvement is particularly notable for images with complex backgrounds,
where our attention mechanism helps the model focus on relevant features.

$$
\mathcal{L}_{total} = \lambda_1 \mathcal{L}_{ce} + \lambda_2 \mathcal{L}_{dice} + \lambda_3 \mathcal{L}_{boundary}
$$
```

## 附录 B：API 请求示例

### 使用 curl 调用 API

```bash
# 上传并转换
curl -X POST http://localhost:8000/api/v1/convert \
  -H "Authorization: Bearer your-api-key" \
  -F "file=@paper.pdf" \
  -F 'config={"vlm": {"model": "qwen-vl-max"}, "general": {"render_dpi": 300}}'

# 查询任务状态
curl http://localhost:8000/api/v1/tasks/{task_id} \
  -H "Authorization: Bearer your-api-key"

# 下载结果
curl -O http://localhost:8000/api/v1/files/{task_id}/result.zip \
  -H "Authorization: Bearer your-api-key"
```

### 使用 Python requests 调用 API

```python
import requests

# 上传并转换
with open("paper.pdf", "rb") as f:
    resp = requests.post(
        "http://localhost:8000/api/v1/convert",
        headers={"Authorization": "Bearer your-api-key"},
        files={"file": f},
        data={"page_range": "1-5"}
    )
task = resp.json()

# 轮询状态
import time
while True:
    status = requests.get(
        f"http://localhost:8000/api/v1/tasks/{task['task_id']}",
        headers={"Authorization": "Bearer your-api-key"}
    ).json()
    if status["status"] in ("completed", "failed"):
        break
    time.sleep(2)

# 获取结果
result = requests.get(
    f"http://localhost:8000/api/v1/tasks/{task['task_id']}/result",
    headers={"Authorization": "Bearer your-api-key"}
).json()
print(result["result"]["markdown"])
```
