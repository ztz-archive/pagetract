# pagetract — 让大模型读懂一切文档

## 项目需求文档 v3.0

**变更记录**：

| 版本 | 日期 | 主要变更 |
|------|------|----------|
| v1.0 | — | 初版，聚焦扫描件 PDF |
| v2.0 | 2026-03-22 | 扩展为通用 PDF 处理；新增 API 服务与 Demo 网站 |
| v2.1 | 2026-03-22 | 多专家评审优化：页面预处理/缓存/流水线并行/成本控制/跨页合并等 |
| **v3.0** | **2026-03-24** | **重新定位项目方向：从"PDF 转 Markdown"升级为"将大模型不能读取的内容转化成大模型能读取的内容"；扩展输入格式支持（图片文件）；输出面向 LLM 消费优化；调整叙事框架** |

---

## 1. 项目概述

### 1.1 项目定位

**pagetract 是一个面向 AI 时代的文档内容转化工具，核心使命是：将大模型不能读取的内容，转化成大模型能读取的结构化内容。**

大语言模型（LLM）正在成为知识工作的核心基础设施，但它们面临一个根本瓶颈：**大量有价值的文档内容以 LLM 无法直接读取的形式存在**——扫描件 PDF、拍照文档、复杂排版的学术论文、嵌入图片的报告等。这些内容中的文字、表格、公式、图片信息，对 LLM 来说就像一面墙。

pagetract 的定位就是**打破这面墙**：通过 CV 布局检测 + VLM 视觉理解的混合架构，将这些"不可读"内容高精度地转化为 LLM 可直接消费的结构化文本（Markdown）。

### 1.2 什么是"大模型不能读取的内容"？

| 内容类型 | 为什么 LLM 不能读 | pagetract 的解决方案 |
|----------|-------------------|---------------------|
| **扫描件 PDF** | 整页是图片，无文本层，LLM 无法提取文字 | 渲染 → CV 布局检测 → VLM 识别全部内容 |
| **低质量 OCR PDF** | 有文本层但是乱码/错位，LLM 读到的是垃圾数据 | 智能检测文本层质量，不可信则走 VLM 路径 |
| **含公式的学术 PDF** | 公式字体无法被文本提取，LLM 看到的是乱码符号 | 检测公式区域，VLM 精确转换为 LaTeX |
| **复杂表格 PDF** | 表格结构在文本层中丢失，LLM 无法理解行列关系 | CV 定位表格区域，VLM 还原为 Markdown/HTML 表格 |
| **多栏排版文档** | 文本提取顺序错乱（跨栏混读），LLM 获取的上下文是乱的 | 多栏检测 + 阅读顺序校正，输出正确的语义顺序 |
| **图文混排文档** | 图片中的关键信息（图表、示意图）LLM 完全忽略 | 提取图片 + 生成描述性 alt text，让 LLM 知道图里有什么 |
| **旋转/倾斜扫描件** | 即使 VLM 也难以处理严重旋转的页面 | 自动旋转/去倾斜预处理，再送识别 |
| **独立图片文件** | 拍照的文档、截图中的文字/表格，LLM 无法直接处理 | 支持图片直接输入，同样走 CV + VLM 流程 |

### 1.3 核心设计理念

采用**"CV 定位 + VLM 全页理解"的混合架构**：

- **布局检测**交给专用 CV 模型（快、准、稳），负责定位和分类页面中的各区域，输出区域坐标与类型
- **内容识别**交给大参数量视觉 LLM（如 Qwen3.5-plus、GPT-4o 等），**以整页图片 + 区域坐标提示的方式**送入，让 VLM 在完整上下文中精准识别目标区域内容，追求极致精度
- **图片提取**由 CV 坐标定位后裁剪保存，保留原始图片质量
- **原生文本层**优先直接提取，公式/复杂表格自动回退到 VLM 识别
- **页面预处理**自动检测并校正旋转、倾斜、颜色反转等问题
- 各模块各司其职，通过标准化的中间数据格式解耦

### 1.4 目标用户场景

pagetract 服务于所有需要"让 LLM 读懂文档"的场景：

| 场景 | 说明 |
|------|------|
| **RAG 数据准备** | 为大模型知识库准备高质量文档数据——这是最核心的场景。各类 PDF、扫描件转为 LLM 可检索的结构化文本 |
| **AI Agent 文档理解** | Agent 需要阅读用户上传的文档（合同、报告、论文），pagetract 作为前置处理层 |
| **学术研究** | 将论文 PDF（扫描版或数字版）转为可编辑的 Markdown，便于引用、批注、喂给 LLM 做分析 |
| **文档数字化** | 将历史扫描档案、报告转为结构化文本，纳入 AI 知识管理体系 |
| **开发者集成** | 通过 API/SDK 将文档转化能力嵌入自有 AI 系统 |

### 1.5 支持的输入格式

| 输入格式 | 说明 | 处理策略 |
|----------|------|----------|
| **纯扫描件 PDF** | 整页都是图片，无文本层 | 渲染为图片 → CV 布局检测 → VLM 识别 |
| **原生数字 PDF** | 有完整文本层、矢量图形 | 优先提取文本层；公式/复杂表格/图片仍走 CV + VLM |
| **图文混合 PDF** | 部分页有文本层，部分页是扫描图 | 逐页判断，文本区域直接提取 + 图片/公式区域走 VLM |
| **学术论文 PDF** | 双栏/多栏排版，含公式、表格、引用 | 多栏检测 + 阅读顺序校正 + VLM 识别公式与表格 |
| **报告/书籍 PDF** | 图文混排，含页眉页脚、目录 | 完整区域检测与分类 |
| **低质量扫描件** | 倾斜、旋转、模糊、颜色反转 | 预处理（去倾斜/旋转/反色校正）后走标准流程 |
| **图片文件** | JPG/PNG/TIFF/BMP 等独立图片（拍照文档、截图） | 直接作为页面图片送入 CV + VLM 流程 |

### 1.6 输出目标：LLM-Ready 的结构化内容

pagetract 的输出不仅仅是"好看的 Markdown"，而是**LLM 能高效理解和利用的结构化文本**：

| 输出特征 | 为什么对 LLM 重要 |
|----------|-------------------|
| **正确的语义顺序** | LLM 按顺序消费文本，阅读顺序错乱会导致上下文污染 |
| **结构化的表格** | Markdown/HTML 表格格式让 LLM 能理解行列关系、比较数据 |
| **LaTeX 格式的公式** | LLM 能精确理解和推理数学公式 |
| **图片的文字描述** | LLM 无法看图，但能通过 alt text 知道图片内容 |
| **清晰的层级标题** | 帮助 LLM 建立文档结构认知，支持 RAG 分块 |
| **干净无噪声** | 页眉页脚、水印等噪声被过滤，不干扰 LLM 理解 |
| **来源标记** | 页码/区域标注帮助 RAG 系统定位原文出处 |

### 1.7 产品交付形式

| 形式 | 说明 |
|------|------|
| **Python SDK** | 核心库，支持同步/异步调用，可嵌入任意 Python 项目 |
| **API 服务** | 基于 FastAPI 的 HTTP API，提供完整的文档转换服务 |
| **Demo 网站** | 可视化体验页面，用于项目测试与展示（Gradio 快速 Demo） |

### 1.8 与同类项目的差异

| 对比项 | MinerU | Zerox / gptpdf | pagetract |
|--------|--------|----------------|------------|
| 核心定位 | 文档解析工具 | VLM PDF 转换 | **LLM 内容可读化** |
| 布局检测 | 自带 DocLayout-YOLO | 无 | 可插拔 CV 模型 |
| OCR 引擎 | 自带小模型 / VLM | 全靠 VLM | 大参数 VLM（可配置） |
| 图片提取 | ✅ 支持 | ❌ 不支持 | ✅ 支持 + alt text 生成 |
| 图片文件输入 | ❌ | ❌ | ✅ 直接处理图片文件 |
| 扫描件支持 | ✅ | 有限（无图片提取） | ✅ 专门优化 |
| 原生 PDF 支持 | ✅ | 有限 | ✅ 文本层优先 + VLM 补充 |
| VLM 可替换 | 仅限自带模型 + llm-aided | 支持多 provider | 完全可插拔 |
| API 服务 | ❌ | ❌ | ✅ RESTful API + SSE 实时进度 |
| 在线 Demo | ❌ | ❌ | ✅ 可视化、逐页对比 |
| 缓存优化 | 部分 | ❌ | ✅ 三层缓存（布局/VLM/文档） |
| 输出优化 | 面向人类阅读 | 面向人类阅读 | **面向 LLM 消费优化** |

---

## 2. 系统架构

### 2.1 整体流程

```
输入: PDF 文档 / 图片文件（JPG、PNG、TIFF 等）
  │
  ▼
[模块I] 输入适配器
  │  PDF → 走 PDF 处理流程
  │  图片文件 → 直接作为页面图片
  ▼
  ┌──── PDF 路径 ────┐     ┌── 图片路径 ──┐
  ▼                   │     ▼              │
[模块Z] PDF 类型检测器 │   跳过类型检测      │
  │  逐页判断:         │                    │
  │  scanned/native/   │                    │
  │  mixed             │                    │
  ▼                    │                    │
  ┌─── 分支判断 ───┐   │                    │
  │                 │   │                    │
  │ scanned/mixed   │ native               │
  ▼                 ▼   │                    │
[G] 预处理器    [A'] 原生提取              │
  ▼                 │   │                    │
[A] PDF 渲染器      │   │                    │
  │                 │   │                    │
  ▼                 ▼   │                    │
  ├─────────────────┘   │                    │
  │                     │                    │
  ▼◄────────────────────┘◄───────────────────┘
[模块B] 布局检测引擎
  │  区域检测 + 分类 + 多栏检测
  │  阅读顺序校正
  ▼
[模块C] 区域处理器
  │  整页+坐标送VLM / 图片裁剪保存
  │  支持同页区域批量合并
  ▼
[模块D] VLM OCR 引擎
  │  整页图片 + 坐标提示 → 内容识别
  │  输出校验 (VLM 结果合理性检查)
  ▼
  └──────────── 合并 ─────────────────┘
                  │
                  ▼
[模块H] 跨页元素合并器
  │  检测并合并跨页表格、跨页段落
  ▼
[模块F] Markdown 组装器
  │  按阅读顺序拼装所有识别结果
  │  面向 LLM 消费优化输出
  ▼
输出: LLM-Ready 结构化 Markdown + images/ 目录 + metadata.json
```

### 2.2 流水线并行架构

核心的性能优化：**不等前序步骤全部完成，后续步骤可流水线并行**。

```
Page 1:  [渲染]  →  [检测]  →  [VLM调用]  → done
Page 2:           [渲染]  →  [检测]  →  [VLM调用]  → done
Page 3:                    [渲染]  →  [检测]  →  [VLM调用]  → done
                                                       ↓
                                              [跨页合并] → [Markdown 组装]
```

使用 `asyncio.Queue` 实现，各阶段之间设缓冲区（`maxsize=3`），控制内存占用：

```python
async def streaming_pipeline(pdf_path):
    render_queue = asyncio.Queue(maxsize=3)
    detect_queue = asyncio.Queue(maxsize=3)
    
    async def render_worker():
        for page in pages_to_render:
            img = render_page(page)
            await render_queue.put((page.number, img))
        await render_queue.put(None)
    
    async def detect_worker():
        while (item := await render_queue.get()) is not None:
            page_num, img = item
            blocks = layout_detect(img)
            await detect_queue.put((page_num, img, blocks))
        await detect_queue.put(None)
    
    async def vlm_worker():
        while (item := await detect_queue.get()) is not None:
            page_num, img, blocks = item
            results = await vlm_batch_recognize(img, blocks)
            collect_results(page_num, results)
    
    await asyncio.gather(render_worker(), detect_worker(), vlm_worker())
```

### 2.3 目录结构约定

```
output/
├── document.md           # LLM-Ready 的结构化 Markdown
├── images/               # 提取的图片
│   ├── page1_fig1.png
│   ├── page1_fig2.png
│   └── page3_table1.png  # 复杂表格同时保存为图片备份
└── metadata.json         # 处理元数据（页数、区域统计、耗时、成本、页类型等）
```

---

## 3. 模块详细设计

### 3.1 模块I：输入适配器（新增）

**职责**：统一不同输入格式的处理入口，将各种输入归一化为后续流程可处理的标准格式。

**设计理念**：pagetract 的核心能力是"让不可读内容变可读"，输入不应限于 PDF。输入适配器是扩展输入格式的统一入口。

```python
class InputAdapter:
    def load(self, input_path: str | Path) -> DocumentInput:
        """
        根据文件类型分发到对应的加载器：
        - .pdf → PDFLoader：返回 PDF 文档对象
        - .jpg/.png/.tiff/.bmp/.webp → ImageLoader：包装为单页文档
        - 目录 → BatchLoader：递归加载目录下所有支持的文件
        """
        ...

@dataclass
class DocumentInput:
    source_path: Path
    input_type: InputType       # "pdf" | "image" | "batch"
    pages: list[PageInput]      # 归一化后的页面列表
    original_metadata: dict     # 原始文件的元信息

class InputType(Enum):
    PDF = "pdf"
    IMAGE = "image"

@dataclass
class PageInput:
    page_number: int
    source_type: InputType
    pdf_page: fitz.Page | None       # PDF 页面对象（仅 PDF 输入）
    image: PIL.Image.Image | None    # 页面图片（图片输入，或已渲染的 PDF 页）
    page_type: PageType | None       # 页面类型（PDF 经检测后填充）
```

**图片输入处理**：

```
图片文件输入:
1. 加载图片 → 包装为 PageInput(source_type=IMAGE, page_type=SCANNED)
2. 跳过 PDF 类型检测（图片天然是"扫描件"）
3. 直接进入预处理 → 布局检测 → VLM 识别 流程
```

**支持的图片格式**：

| 格式 | 扩展名 |
|------|--------|
| JPEG | .jpg, .jpeg |
| PNG | .png |
| TIFF | .tiff, .tif |
| BMP | .bmp |
| WebP | .webp |

**配置项**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `supported_image_formats` | list[str] | [".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp"] | 支持的图片格式 |
| `max_image_pixels` | int | 25_000_000 | 单张图片最大像素数（防止内存溢出） |

---

### 3.2 模块Z：PDF 类型检测器

**职责**：逐页判断 PDF 的类型，决定后续处理策略。仅对 PDF 输入生效。

**检测逻辑**：

```python
class PageType(Enum):
    SCANNED = "scanned"    # 纯扫描件页：无文本层 或 文本层为低质量 OCR 垃圾
    NATIVE = "native"      # 原生数字页：有完整且可信的文本层
    MIXED = "mixed"        # 混合页：有文本层但也包含大面积嵌入图片/公式

@dataclass
class PageClassification:
    page_number: int
    page_type: PageType
    text_coverage: float
    text_layer_quality: float
    quality_metrics: TextQualityMetrics
    quality_reason: str
    has_embedded_images: bool
    has_formula_fonts: bool
    detected_languages: list[str]
```

**文本层质量评估算法**：

```python
@dataclass
class TextQualityMetrics:
    char_count: int
    invalid_char_ratio: float
    cjk_char_ratio: float
    font_count: int
    avg_char_width_variance: float
    language_coherence: float

def evaluate_text_quality(pdf_page) -> TextQualityMetrics:
    """
    计算文本层质量，关键指标：
    1. 无效字符率 > 5% → 质量极低
    2. 字体数 > 20 → 可能有问题
    3. 字符位置分散 → 低质量 OCR 特征
    4. 检测公式字体 (CMMI, Cambria Math 等) → 标记 has_formula_fonts
    """
    ...
```

**判断策略**：

```
1. 提取页面文本层
   → 文本为空或字符数 < min_text_chars → SCANNED
2. 文本层质量检测
   → 无效字符率 > 5% → SCANNED (低质量 OCR 文本层)
   → 字符位置严重分散 → SCANNED
   → quality_score < text_quality_threshold → SCANNED
3. 检查嵌入图片面积
   → 图片面积 > 页面 30% → MIXED
4. 检测公式字体
   → 有公式字体 → MIXED（即使文本层可信，公式仍需 VLM）
5. 以上都不满足 → NATIVE
```

**mixed 页面的细化策略**：对于 MIXED 页面，文本区域直接提取，公式/图片/复杂表格区域走渲染 + VLM 路径。仅对无法文本提取的区域调用 VLM，显著降低处理成本。

**配置项**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `force_mode` | str \| None | None | 强制模式：`"scanned"` / `"native"` / `None`自动 |
| `text_quality_threshold` | float | 0.7 | 质量低于此值视为不可信 |
| `min_text_chars` | int | 20 | 字符数低于此值视为无文本层 |
| `formula_font_patterns` | list[str] | ["CMMI", "CMBX", "Cambria Math", "STIXGeneral"] | 公式字体名称模式 |

---

### 3.3 模块G：页面预处理器

**职责**：对扫描件/混合页面/图片输入进行预处理，包括旋转校正、去倾斜、颜色反转检测。

**处理流程**：

```python
class PagePreprocessor:
    def preprocess(self, image: PIL.Image.Image) -> PreprocessResult:
        """
        依次执行：
        1. 旋转检测与校正（90°/180°/270° 整体旋转）
        2. 倾斜检测与校正（0.5°-5° 的微小倾斜，使用 deskew 库）
        3. 颜色反转检测（白字黑底 → 反色为黑字白底）
        """
        ...

@dataclass
class PreprocessResult:
    image: PIL.Image.Image
    rotation_applied: int
    skew_corrected: float
    was_inverted: bool
```

**旋转检测方法**：优先用 Tesseract OSD（快），失败时用 OpenCV Hough 变换检测文字方向。

**配置项**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enable_rotation_correction` | bool | True | 自动旋转校正 |
| `enable_deskew` | bool | True | 自动去倾斜 |
| `deskew_threshold_degrees` | float | 0.5 | 倾斜角度超过此值才校正 |
| `enable_inversion_detection` | bool | True | 自动检测颜色反转 |

---

### 3.4 模块A：PDF 页面渲染器

**职责**：将 PDF 每页渲染为高分辨率位图（主要用于 scanned / mixed 页面）。对图片输入跳过此模块。

**技术选型**：`PyMuPDF (fitz)` 或 `pdf2image (poppler)`

**超长页面处理**：对于高度超过 `max_page_height_px` 的页面，自动分割为多个子图片分别处理：

```python
def render_with_height_check(pdf, page_num, dpi=300):
    page_height_px = get_page_height(pdf, page_num) * dpi / 72
    
    if page_height_px > config.max_page_height_px:
        return split_vertical(pdf, page_num, 
                              split_height=config.split_height, 
                              overlap=config.split_overlap)
    return [render_page(pdf, page_num, dpi=dpi)]
```

**配置项**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `render_dpi` | int | 300 | 渲染分辨率 |
| `image_format` | str | "png" | 输出格式 |
| `page_range` | list[int] \| None | None | 指定页码范围 |
| `max_page_height_px` | int | 4000 | 超长页面阈值（像素） |
| `split_height` | int | 3200 | 分割子图片高度 |
| `split_overlap` | int | 200 | 分割重叠区域（像素） |

**输出**：`list[PageImage]`

```python
@dataclass
class PageImage:
    page_number: int
    image: PIL.Image.Image
    width: int
    height: int
    is_split: bool = False
    split_index: int = 0
```

---

### 3.5 模块A'：原生文本提取器

**职责**：对 `NATIVE` / `MIXED` 类型的 PDF 页面，直接从文本层提取结构化内容。

**技术选型**：`PyMuPDF (fitz)` 的文本提取 API

**提取内容**：

```python
@dataclass
class NativePageContent:
    page_number: int
    text_blocks: list[TextBlock]
    embedded_images: list[EmbeddedImage]
    tables: list[NativeTable] | None
    needs_vlm_fallback: list[FallbackRegion]

@dataclass
class TextBlock:
    text: str
    bbox: tuple[int, int, int, int]
    font_size: float
    font_name: str
    is_bold: bool
    is_italic: bool

@dataclass
class FallbackRegion:
    """需要回退到渲染+VLM的区域"""
    bbox: tuple[int, int, int, int]
    reason: str   # "formula" | "complex_table" | "garbled_text"
```

**回退逻辑**：

```
原生页面提取后，检查以下情况：
1. 检测到公式字体 → FallbackRegion(reason="formula")
2. 表格结构不完整 → FallbackRegion(reason="complex_table")
3. 提取的文本含乱码片段 → FallbackRegion(reason="garbled_text")

对标记的 fallback 区域：渲染该页面 → 仅对 fallback 区域走 VLM 路径
对其余文本区域：直接使用提取结果
```

**配置项**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `fallback_to_vlm` | bool | True | 是否对公式/复杂表格自动回退到 VLM |
| `formula_font_patterns` | list[str] | ["CMMI", "CMBX", "Cambria Math"] | 公式字体检测 |
| `garbled_text_threshold` | float | 0.05 | 乱码字符率超过此值则回退 |

---

### 3.6 模块B：布局检测引擎

**职责**：对页面图片进行区域检测和分类。

**设计要求**：可插拔架构，通过适配器模式支持不同的布局检测后端。

**默认后端**：`DocLayout-YOLO`

**抽象接口**：

```python
class LayoutDetector(Protocol):
    def detect(self, image: PIL.Image.Image) -> list[LayoutBlock]:
        ...

@dataclass
class LayoutBlock:
    block_type: BlockType
    bbox: tuple[int, int, int, int]
    confidence: float
    reading_order: int
    page_number: int
    column_id: int | None = None

class BlockType(Enum):
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
```

**多栏检测与阅读顺序校正**：

```python
def detect_and_reorder(self, image) -> list[LayoutBlock]:
    blocks = self._raw_detect(image)
    columns = self._detect_columns(image, blocks)
    
    if len(columns) > 1:
        for block in blocks:
            block.column_id = self._assign_column(block.bbox, columns)
        blocks.sort(key=lambda b: (b.column_id, (b.bbox[1] + b.bbox[3]) / 2))
        for i, b in enumerate(blocks):
            b.reading_order = i
    
    return blocks
```

**配置项**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `confidence_threshold` | float | 0.5 | 低于此值的检测结果丢弃 |
| `merge_adjacent_text` | bool | True | 是否合并相邻的 text 区域 |
| `detect_reading_order` | bool | True | 是否进行阅读顺序排序 |
| `detect_columns` | bool | True | 是否进行多栏检测 |
| `discard_types` | list[str] | ["header", "footer", "page_number"] | 默认丢弃的区域类型 |

---

### 3.7 模块C：区域处理分发器

**职责**：根据区域类型分发到不同的处理器。采用**"整页送 VLM + 坐标提示"**的策略。

**设计理念**：

CV 模型已精确定位各区域的坐标和类型。模块C 的核心职责是：
- **内容识别类**区域：将**整页图片 + 目标区域坐标**一起送给 VLM，让 VLM 在完整上下文中理解并识别
- **图片类**区域：仅按坐标裁剪保存像素，不需要 VLM 的"理解"能力

核心优势：
- VLM 能看到目标区域**周围的上下文**，不怕 bbox 略有偏差
- 公式、表格等 bbox 容易切偏的区域，VLM 可自行判断实际边界，**精度显著提升**
- 同一页面的多个相邻区域可**合并为一次 VLM 请求**，减少调用次数

**核心逻辑**：

```
对每个 LayoutBlock（按页分组）:
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

**同页区域智能批量合并**：

```python
def smart_batch_regions(page_blocks: list[LayoutBlock], config) -> list[VLMRequest]:
    """
    将同页区域智能分组为批量 VLM 请求，减少 API 调用次数。
    规则：
    - 同类型 + 相邻（距离 < max_region_distance）→ 合并
    - 每个 batch 最多 max_regions_per_batch 个区域
    - 复杂页面（区域数 > complexity_threshold）采用更保守的分组
    """
    ...
```

**动态坐标调整**：根据置信度和区域类型，动态扩展 bbox 边界传给 VLM：

```python
def adjust_bbox_for_vlm(bbox, block_type, confidence):
    expansion = int(10 * (1 - confidence))
    if block_type == BlockType.TABLE:
        expansion = max(expansion, 15)
    elif block_type == BlockType.FORMULA:
        expansion = max(expansion, 8)
    return expand_bbox(bbox, expansion, page_bounds)
```

---

### 3.8 模块D：VLM OCR 引擎

**职责**：调用大参数量视觉 LLM 对页面中的指定区域进行高精度内容识别。VLM 接收**整页图片 + 目标区域坐标**，在完整上下文中精准识别。

**设计要求**：
- 通过 OpenAI 兼容 API 接口统一接入，支持任意 VLM provider
- 接收整页图片和区域坐标，在 prompt 中指示 VLM 聚焦目标区域
- 支持同页多区域批量识别
- 不同区域类型使用不同的 system prompt
- 支持并发请求以提升吞吐
- 支持重试和错误处理

**抽象接口**：

```python
class VLMEngine(Protocol):
    async def recognize(
        self,
        page_image: PIL.Image.Image,
        target_bbox: tuple[int, int, int, int],
        block_type: BlockType,
        context: str | None = None
    ) -> RecognitionResult:
        ...

    async def recognize_batch(
        self,
        page_image: PIL.Image.Image,
        targets: list[tuple[tuple[int, int, int, int], BlockType]],
        context: str | None = None
    ) -> list[RecognitionResult]:
        ...

@dataclass
class RecognitionResult:
    content: str
    content_type: str          # "text" | "latex" | "markdown_table" | "html_table"
    confidence: float | None
    target_bbox: tuple[int, int, int, int]
    raw_response: str
    validation_passed: bool = True
    validation_warning: str = ""
```

**各区域类型的 Prompt 策略**：

所有 prompt 均包含坐标区域信息，指引 VLM 聚焦目标区域。prompt 设计面向"为 LLM 生成可消费内容"优化：

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
  请将图片中坐标区域 ({x1}, {y1}) 到 ({x2}, {y2}) 范围内的表格
  精确转换为 Markdown 表格格式。
  要求：
  - 只关注指定坐标区域内的表格
  - 表头用 | --- | 分隔
  - 保持行列结构完全一致
  - 如果表格过于复杂无法用 Markdown 表示，请使用 HTML <table> 标签
  - 不要输出任何解释性文字

formula_prompt: |
  请将图片中坐标区域 ({x1}, {y1}) 到 ({x2}, {y2}) 范围内的数学公式
  转换为 LaTeX 格式。
  要求：
  - 只关注指定坐标区域内的公式
  - 用 $$ $$ 包裹行间公式
  - 精确还原所有数学符号、上下标、分数、积分等
  - 不要输出任何解释性文字，只输出 LaTeX 代码

caption_prompt: |
  请识别图片中坐标区域 ({x1}, {y1}) 到 ({x2}, {y2}) 范围内的说明文字。
  只输出文本内容。

image_alt_prompt: |
  请观察图片中坐标区域 ({x1}, {y1}) 到 ({x2}, {y2}) 范围内的图片内容，
  用一句简洁的中文描述概括图片内容，用于帮助大语言模型理解该图片。不要超过 50 个字。

batch_prompt: |
  你是一个专业的 OCR 系统。图片是一个完整的文档页面。
  请依次识别以下各坐标区域的内容，每个区域的结果用 [REGION_N] 标记分隔：
  {regions_description}
  要求：
  - 对每个区域，只识别该坐标范围内的内容
  - 逐字精确，保留格式
  - 用 [REGION_1], [REGION_2], ... 标记各区域结果的开头
```

**VLM 图片预处理**（成本优化）：

在送入 VLM 前，对整页图片进行降采样以控制 token 消耗：

```python
def prepare_image_for_vlm(page_image, config):
    ratio = config.vlm_downsample_ratio  # 默认 0.7
    new_w = int(page_image.width * ratio)
    new_h = int(page_image.height * ratio)
    downsampled = page_image.resize((new_w, new_h), Image.Resampling.LANCZOS)
    return downsampled, ratio
```

**VLM 输出校验**：

```python
class VLMResponseValidator:
    def validate(self, result: RecognitionResult, block: LayoutBlock,
                 page_image: PIL.Image.Image) -> RecognitionResult:
        """
        校验 VLM 输出的合理性:
        1. TEXT: 用快速 OCR 对裁剪区域做对比，词汇重叠率 < 60% 则标记警告
        2. TABLE: 检查行数是否与 bbox 面积匹配
        3. FORMULA: 检查是否包含有效的 LaTeX 语法
        4. 通用: 输出长度与区域面积的比例是否合理
        """
        ...
```

**配置项**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `api_base_url` | str | — | OpenAI 兼容 API 地址 |
| `api_key` | str | — | API 密钥 |
| `model` | str | "qwen-vl-max" | 模型名称 |
| `max_concurrent` | int | 15 | 最大并发请求数 |
| `connection_pool_size` | int | 20 | HTTP 连接池大小 |
| `timeout` | int | 60 | 单次请求超时秒数 |
| `max_retries` | int | 3 | 失败重试次数 |
| `temperature` | float | 0.1 | 生成温度 |
| `recognition_mode` | str | "full_page" | `full_page`(整页+坐标) / `crop`(裁剪小图，兼容模式) |
| `vlm_downsample_ratio` | float | 0.7 | 送 VLM 前的降采样比例 |
| `batch_regions` | bool | True | 同页相邻区域合并为一次请求 |
| `max_regions_per_batch` | int | 5 | 单次批量请求最多区域数 |
| `max_region_distance` | int | 500 | 合并区域的最大间距(px) |
| `complexity_threshold` | int | 15 | 页面区域数超过此值采用保守策略 |
| `enable_output_validation` | bool | True | 是否校验 VLM 输出 |
| `generate_image_alt` | bool | True | 是否为图片生成 alt 描述 |
| `custom_prompts` | dict | {} | 自定义 prompt，覆盖默认 |
| `document_context` | str | "" | 文档上下文描述 |

**Provider 预设**：

```yaml
providers:
  dashscope:
    api_base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model: "qwen-vl-max"
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

### 3.9 模块E：图片保存器

**职责**：将检测为 image 类型的区域按坐标裁剪保存为独立文件。

**命名规则**：`page{页码}_fig{序号}.png`

**原生 PDF 图片提取**：对于 `NATIVE` 页面，优先直接从 PDF 中提取嵌入图片对象。

**alt text 生成策略**（面向 LLM 优化）：

图片的 alt text 是 LLM 理解文档视觉信息的唯一途径，优先级极高：

```
1. 优先使用相邻 caption（由布局检测发现的 CAPTION 区域）
2. 无 caption 且图片面积 > 页面 10% → 调用 VLM 生成描述
3. 小图片无 caption → 使用默认描述 "Page X, Figure Y"
```

**配置项**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `image_format` | str | "png" | 保存格式 |
| `image_quality` | int | 95 | JPEG 质量 |
| `min_image_size` | int | 50 | 宽或高小于此值(px)忽略 |
| `padding` | int | 5 | 裁剪外扩像素数 |
| `save_table_images` | bool | True | 是否保存表格区域图片备份 |
| `prefer_embedded` | bool | True | 原生 PDF 优先提取嵌入图片 |

---

### 3.10 模块H：跨页元素合并器

**职责**：检测并合并跨页表格、跨页段落等连续元素。

**检测逻辑**：

```python
class CrossPageAggregator:
    def detect_cross_page_elements(self, all_blocks, page_images):
        """
        检测可能跨页的元素:
        - 页面底部 (y2 > 页面高度 95%) 有 block
        - 下一页顶部 (y1 < 页面高度 5%) 有同类型 block
        - 两个 block 类型相同
        """
        ...
```

**合并策略**：
- **跨页表格**：合并为一个完整的 Markdown 表格（去掉重复的表头）
- **跨页段落**：拼接为一个连续段落
- **跨页公式**：合并为一个完整的 LaTeX 公式块

---

### 3.11 模块F：Markdown 组装器

**职责**：按阅读顺序将所有处理结果拼装为最终 Markdown 文件。输出面向 LLM 消费优化。

**组装规则**：

```
1. 按 page_number 排序，同页内按 reading_order 排序
2. 合并来自 scanned 路径和 native 路径的结果
3. 应用跨页合并结果
4. 页与页之间插入分页标记（可配置）
5. 不同类型的内容使用不同的 Markdown 语法：
   - TITLE → # / ## / ### (根据字号或位置推断层级)
   - TEXT → 段落文本，段落间空行分隔
   - IMAGE → ![alt_text](images/pageX_figY.png)
   - TABLE → Markdown/HTML 表格
   - FORMULA → $$ LaTeX $$
   - CAPTION → 紧跟关联的 image/table，用 *斜体* 标记
   - LIST → 列表格式
   - CODE → ``` 代码块 ```
   - REFERENCE → 文档末尾参考文献区
6. 每个 Markdown 片段标记来源：<!-- Source: page X, block Y -->
```

**LLM 消费优化**：
- 确保输出的语义顺序正确，避免跨栏错读
- 过滤页眉页脚等噪声信息
- 图片以 alt text 形式呈现（LLM 无法直接看图片引用链接）
- 来源标记便于 RAG 系统回溯原文位置

**配置项**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `page_separator` | str | "\n\n---\n\n" | 页间分隔符 |
| `include_page_markers` | bool | True | 插入 `<!-- Page X -->` 标记 |
| `include_source_markers` | bool | True | 每个片段的来源标记 |
| `image_ref_style` | str | "relative" | 图片引用：relative / absolute / base64_inline |
| `title_level_strategy` | str | "auto" | 标题层级推断：auto / flat / positional |
| `discard_header_footer` | bool | True | 丢弃页眉页脚 |

---

## 4. 缓存系统设计

### 4.1 三层缓存架构

```
┌──────────────────────────────────────┐
│ L1: 布局检测结果缓存 (内存+磁盘)      │ TTL: 24h
├──────────────────────────────────────┤
│ L2: VLM 响应缓存 (磁盘)              │ TTL: 7天
├──────────────────────────────────────┤
│ L3: 文档完整结果缓存 (磁盘)           │ TTL: 30天
└──────────────────────────────────────┘
```

- **L1 布局缓存**：cache key = `MD5(文件内容) + page_number`。重复处理跳过布局检测。
- **L2 VLM 缓存**：cache key = `MD5(文件) + page + bbox + block_type + model`。重复识别跳过 VLM 调用。
- **L3 文档缓存**：cache key = `MD5(文件) + page_range + config_hash`。完全相同的请求秒级返回。

**配置项**：

```yaml
cache:
  enable: true
  directory: "./cache"
  max_size_mb: 500
  eviction_policy: "lru"
  layout_cache_ttl_hours: 24
  vlm_cache_ttl_days: 7
  document_cache_ttl_days: 30
```

---

## 5. API 服务设计

### 5.1 技术选型

- **框架**：FastAPI
- **实时进度**：SSE (Server-Sent Events)
- **任务队列**：FastAPI BackgroundTasks
- **文件存储**：本地磁盘

### 5.2 API 端点设计

#### 5.2.1 文档转换

```
POST /api/v1/convert
```

**请求**：`multipart/form-data`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | File | ✅ | PDF 文件或图片文件 |
| `config` | JSON string | ❌ | 覆盖默认转换配置 |
| `page_range` | string | ❌ | 页码范围（仅 PDF），如 `"1-5,8,10"` |
| `callback_url` | string | ❌ | 转换完成后的回调 URL |

**响应**（同步模式）：

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
      "input_type": "pdf",
      "total_pages": 12,
      "processing_time_seconds": 45.2,
      "api_calls": 24,
      "estimated_cost_yuan": 0.84,
      "page_types": {"scanned": 8, "native": 4},
      "cache_hits": {"layout": 0, "vlm": 0}
    }
  }
}
```

**响应**（异步模式，大文件）：HTTP 202 Accepted

```json
{
  "task_id": "uuid-xxxx",
  "status": "processing",
  "events_url": "/api/v1/tasks/{task_id}/events"
}
```

#### 5.2.2 任务状态查询

```
GET /api/v1/tasks/{task_id}
```

#### 5.2.3 SSE 实时进度推送

```
GET /api/v1/tasks/{task_id}/events
```

```
event: progress
data: {"current_page": 5, "total_pages": 12, "percent": 41.7, "stage": "VLM识别: Page 5 表格区域"}

event: completed
data: {"task_id": "uuid-xxxx", "result_url": "/api/v1/tasks/{task_id}/result"}
```

#### 5.2.4 任务取消

```
DELETE /api/v1/tasks/{task_id}
```

#### 5.2.5 获取转换结果

```
GET /api/v1/tasks/{task_id}/result
```

#### 5.2.6 下载结果文件

```
GET /api/v1/files/{task_id}/document.md
GET /api/v1/files/{task_id}/images/{filename}
GET /api/v1/files/{task_id}/result.zip
```

#### 5.2.7 成本预估

```
POST /api/v1/estimate
```

上传文件，仅做类型检测 + 布局检测，返回成本预估：

```json
{
  "input_type": "pdf",
  "total_pages": 12,
  "page_types": {"scanned": 8, "native": 4},
  "estimated_api_calls": 24,
  "estimated_cost_yuan": 0.84,
  "estimated_time_seconds": 15
}
```

#### 5.2.8 配置预检

```
POST /api/v1/validate_config
```

#### 5.2.9 健康检查

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

### 5.3 统一错误格式

```json
{
  "error": {
    "code": "FILE_TOO_LARGE",
    "message": "上传文件大小超过限制 (100MB)",
    "detail": null
  }
}
```

### 5.4 API 配置项

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `host` | str | "0.0.0.0" | 监听地址 |
| `port` | int | 8000 | 监听端口 |
| `max_file_size_mb` | int | 100 | 上传文件大小上限 |
| `max_pages` | int | 200 | 单次转换最大页数 |
| `async_threshold_pages` | int | 10 | 超过此页数自动切换异步模式 |
| `task_ttl_hours` | int | 24 | 任务结果保留时长 |

---

## 6. Demo 网站设计

### 6.1 定位

提供可视化前端，用于快速体验"把 LLM 不可读内容变为可读内容"的转化效果。

### 6.2 技术选型

| 场景 | 方案 | 说明 |
|------|------|------|
| **快速 Demo** | Gradio | 零前端开发，适合快速上线 |
| **生产级 Web** | Vue 3 + Vite + Element Plus | 丰富交互，适合长期维护 |

MVP 阶段先用 Gradio 快速上线。

### 6.3 核心功能

| 功能 | 说明 |
|------|------|
| **文件上传** | 拖拽上传 PDF 或图片文件，显示文件基本信息 |
| **转换选项** | 选择模型、DPI、页码范围等常用参数 |
| **实时进度** | SSE 推送进度，显示进度条与当前处理步骤 |
| **逐页对比** | 左侧原始页面 ↔ 右侧对应 Markdown 渲染，可翻页联动 |
| **源码查看** | 切换为查看原始 Markdown 源码 |
| **结果下载** | 复制 Markdown、下载 .md、下载 .zip |
| **成本预估** | 转换前显示预估成本和耗时 |

---

## 7. 配置系统设计

### 7.1 配置优先级

```
CLI 参数 > 环境变量 > config.yaml > 默认值
```

### 7.2 统一配置文件

```yaml
# pagetract 配置文件

# 全局设置
general:
  render_dpi: 300
  page_range: null
  output_dir: "./output"
  document_context: ""

# 输入适配
input:
  supported_image_formats: [".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp"]
  max_image_pixels: 25000000

# PDF 类型检测
pdf_detection:
  force_mode: null
  text_quality_threshold: 0.7
  min_text_chars: 20
  formula_font_patterns: ["CMMI", "CMBX", "Cambria Math", "STIXGeneral"]

# 页面预处理
preprocessing:
  enable_rotation_correction: true
  enable_deskew: true
  deskew_threshold_degrees: 0.5
  enable_inversion_detection: true

# 布局检测
layout:
  engine: "doclayout-yolo"
  confidence_threshold: 0.5
  merge_adjacent_text: true
  detect_columns: true
  discard_types:
    - header
    - footer
    - page_number

# VLM OCR
vlm:
  provider: "dashscope"
  api_base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  api_key: "${SCANDOC_API_KEY}"
  model: "qwen-vl-max"
  temperature: 0.1
  max_concurrent: 15
  connection_pool_size: 20
  max_retries: 3
  timeout: 60
  recognition_mode: "full_page"
  vlm_downsample_ratio: 0.7
  batch_regions: true
  max_regions_per_batch: 5
  max_region_distance: 500
  complexity_threshold: 15
  enable_output_validation: true
  generate_image_alt: true
  custom_prompts: {}

# 图片提取
image_extraction:
  format: "png"
  min_size: 50
  padding: 5
  save_table_images: true
  prefer_embedded: true

# 缓存
cache:
  enable: true
  directory: "./cache"
  max_size_mb: 500
  eviction_policy: "lru"
  layout_cache_ttl_hours: 24
  vlm_cache_ttl_days: 7
  document_cache_ttl_days: 30

# Markdown 输出
markdown:
  page_separator: "\n\n---\n\n"
  include_page_markers: true
  include_source_markers: true
  image_ref_style: "relative"
  title_level_strategy: "auto"

# 成本控制
cost_control:
  enable_cost_estimation: true
  budget_limit_yuan: null

# API 服务
api:
  host: "0.0.0.0"
  port: 8000
  max_file_size_mb: 100
  max_pages: 200
  async_threshold_pages: 10
  task_ttl_hours: 24

# 内存控制
memory:
  max_cached_pages: 3
```

### 7.3 环境变量

| 环境变量 | 说明 |
|----------|------|
| `SCANDOC_API_KEY` | VLM API 密钥 |
| `SCANDOC_CONFIG` | 配置文件路径（默认 `./config.yaml`） |
| `SCANDOC_SERVER_HOST` | API 服务监听地址 |
| `SCANDOC_SERVER_PORT` | API 服务监听端口 |
| `SCANDOC_ENV` | 环境标识：dev / prod |

---

## 8. CLI 接口设计

### 8.1 子命令结构

```bash
pagetract convert    # 转换文档（PDF 或图片）
pagetract serve      # 启动 API 服务
pagetract config     # 配置管理 (init/show/validate)
pagetract doctor     # 检查环境和依赖
pagetract version    # 版本信息
```

### 8.2 转换命令

```bash
# 转换 PDF
pagetract convert input.pdf -o output/

# 转换图片文件
pagetract convert photo.jpg -o output/

# 指定配置 + 覆盖参数
pagetract convert input.pdf -o output/ --config my_config.yaml --model gpt-4o --dpi 400

# 指定页码范围 + 强制模式
pagetract convert input.pdf -o output/ --pages 1,2,3,5-10 --force-mode scanned

# 批量处理（递归子目录，支持 PDF 和图片混合）
pagetract convert ./docs/ -o output/ --batch --recursive

# 成本预估（dry-run，不调用 VLM）
pagetract convert input.pdf --dry-run

# 仅做布局检测（调试用）
pagetract convert input.pdf -o output/ --layout-only

# JSON 结构化输出
pagetract convert input.pdf -o output/ --output-format json

# 指定最大预算
pagetract convert input.pdf -o output/ --max-cost 5.0

# 使用/不使用缓存
pagetract convert input.pdf -o output/ --no-cache

# 日志级别
pagetract convert input.pdf -o output/ --log-level debug --log-file convert.log
```

### 8.3 服务启动

```bash
pagetract serve --port 9000 --config production.yaml
```

### 8.4 配置管理

```bash
pagetract config init     # 交互式初始化配置文件
pagetract config show     # 显示当前生效的配置
pagetract config validate # 校验配置合法性
```

### 8.5 环境检查

```bash
pagetract doctor
# 输出：
# ✅ Python 3.12
# ✅ PyMuPDF 1.24.0
# ✅ DocLayout-YOLO model loaded
# ✅ VLM API reachable (dashscope, qwen-vl-max)
# ✅ GPU available (CUDA 12.1)
# ⚠️ Tesseract not installed (rotation detection unavailable)
```

---

## 9. Python SDK 接口设计

### 9.1 主入口

```python
from pagetract import PageTract

converter = PageTract(config_path="config.yaml")

# 转换 PDF
result = converter.convert("input.pdf", output_dir="./output")
print(result.markdown)
print(result.metadata.cost_yuan)

# 转换图片
result = converter.convert("photo.jpg", output_dir="./output")
print(result.markdown)

# 异步接口
result = await converter.aconvert("input.pdf", output_dir="./output")

# 成本预估
estimate = converter.estimate("input.pdf")
print(f"预估成本: ¥{estimate.cost_yuan}, 耗时: {estimate.time_seconds}s")
```

### 9.2 逐模块调用（高级用法）

```python
from pagetract import (
    InputAdapter, PDFTypeDetector, PagePreprocessor,
    PDFRenderer, LayoutDetector, VLMEngine, 
    CrossPageAggregator, MarkdownAssembler
)

# Step 0: 输入适配
adapter = InputAdapter()
doc_input = adapter.load("input.pdf")  # 或 "photo.jpg"

# Step 1: 类型检测 (仅 PDF)
if doc_input.input_type == InputType.PDF:
    detector = PDFTypeDetector()
    page_types = detector.classify(doc_input)

# Step 2: 渲染 + 预处理
renderer = PDFRenderer(dpi=300)
preprocessor = PagePreprocessor()
pages = []
for page in doc_input.pages:
    if page.needs_rendering:
        rendered = renderer.render(page)
        pages.append(preprocessor.preprocess(rendered))
    else:
        pages.append(page)

# Step 3: 布局检测
layout = LayoutDetector(engine="doclayout-yolo")
all_blocks = [block for page in pages for block in layout.detect(page.image)]

# Step 4: VLM 识别
vlm = VLMEngine(provider="dashscope", model="qwen-vl-max")
processed = await vlm.process_blocks(all_blocks, pages)

# Step 5: 跨页合并
aggregator = CrossPageAggregator()
merged = aggregator.merge(processed)

# Step 6: Markdown 组装
assembler = MarkdownAssembler()
markdown = assembler.assemble(merged, output_dir="./output")
```

---

## 10. 技术栈

### 10.1 核心依赖

| 组件 | 推荐库 | 用途 |
|------|--------|------|
| PDF 处理 | `PyMuPDF (fitz)` | 渲染 + 文本提取 + 图片提取 |
| 布局检测 | `DocLayout-YOLO` / `ultralytics` | 区域检测和分类 |
| 图片处理 | `Pillow` | 裁剪、保存、预处理、格式转换 |
| 去倾斜 | `deskew` | 扫描件去倾斜 |
| VLM 调用 | `httpx` (async) 或 `openai` SDK | 异步 HTTP 请求 |
| 快速 OCR（校验用） | `PaddleOCR` (可选) | VLM 输出校验 |
| 配置管理 | `pydantic` + `PyYAML` | 配置校验和加载 |
| CLI | `typer` 或 `click` | 命令行接口 |
| 进度显示 | `rich` | 进度条和美化输出 |
| 并发控制 | `asyncio` + `asyncio.Semaphore` | 流水线 + VLM 并发 |
| API 框架 | `FastAPI` + `uvicorn` | HTTP API + SSE |
| 前端（快速Demo） | `Gradio` | 快速上线 |
| 前端（生产级） | `Vue 3` + `Vite` + `Element Plus` | 丰富交互 |

### 10.2 开发环境

- Python >= 3.10
- Node.js >= 18（Vue 前端）
- 包管理：`uv` 或 `pip`（Python），`pnpm`（前端）
- 格式化：`ruff`（Python），`eslint` + `prettier`（前端）
- 类型检查：`pyright` 或 `mypy`

---

## 11. 关键设计决策与权衡

### 11.1 为什么不让 VLM 做布局检测？

- **精度**：专用 YOLO 模型 mAP 达 97.5%，VLM grounding 远不及
- **成本**：每页调用大模型做布局检测太贵
- **速度**：YOLO 毫秒级，VLM 秒级
- **确定性**：CV 模型输出稳定，VLM 可能每次结果不同

结论：CV 负责"在哪"，VLM 负责"是什么"。

### 11.2 为什么送整页图片+坐标而不是裁剪小图？

**核心选择：VLM 始终接收整页图片 + 坐标提示。**

优势：
- **上下文完整**：VLM 能看到目标区域周围的内容，不怕 bbox 略有偏差
- **精度更高**：公式、表格等 bbox 容易切偏的区域，VLM 可自行判断实际边界
- **跨区域关联**：相邻的 caption 和 image 等关系可被自然感知
- **容错更好**：即使 CV 模型的 bbox 有偏移，VLM 依然能识别完整内容

代价与缓解：
- 每次传输整页图片 → token 消耗更大 → 通过**同页区域批量合并 + 70%降采样**缓解
- 实测：合并+降采样后，总成本反而比裁剪方案**低约 50%**

**兼容模式**：提供 `recognition_mode: "crop"` 回退到裁剪小图。

### 11.3 为什么定位为"让 LLM 读懂文档"而不只是"文档转换"？

- **差异化**：同类工具都定位为"文档格式转换"，pagetract 以"LLM 赋能"为定位更有辨识度
- **设计决策导向**：当输出面向 LLM 消费时，设计优先级会不同——语义正确性 > 视觉还原度
- **市场契合**：RAG、Agent 等 LLM 应用正在爆发，"LLM 内容可读化"切中真实痛点
- **扩展方向清晰**：后续扩展输入格式（PPT、Word、网页截图等）有统一的逻辑框架

---

## 12. 错误处理与鲁棒性

### 12.1 VLM 调用失败

- 单次超时 → 自动重试（指数退避，最多 max_retries 次）
- 连续失败 → 记录到 metadata.json，在 Markdown 中插入 `[OCR_FAILED: page X, block Y]`
- VLM 输出校验失败 → 重试一次，仍失败则标记警告并保留结果

### 12.2 VLM 不遵守坐标指令

- 使用快速 OCR 对裁剪区域做对比
- 词汇重叠率 < 60% → 标记警告
- 可配置为自动重试或回退到 crop 模式

### 12.3 布局检测异常

- 某页检测不到任何区域 → 回退到整页送 VLM
- 区域严重重叠 → NMS 去重
- 区域超出页面边界 → 裁剪到边界内
- 超长页面 → 自动分割处理

### 12.4 输入校验

- 不支持的文件格式 → 报错并列出支持的格式
- 空白页 → 跳过，日志记录
- 超大文件 (>1000页) → 警告并建议分批 / 检查预算限制
- 图片像素过大 (>25M pixels) → 自动缩放或报错

### 12.5 API 服务错误

统一错误格式，包含错误码、消息、详情。所有 500 错误附带追踪 ID。

---

## 13. 性能优化

### 13.1 流水线并行

核心优化：渲染、布局检测、VLM 调用流水线并行（见 2.2）。

预期收益（100 页文档）：顺序处理 ~290s → 流水线 ~65s（节省 77%）。

### 13.2 并发策略

```
PDF 渲染: 同步顺序（快）
预处理: 同步（快）
布局检测: 可并行（GPU 显存允许时）
VLM 调用: asyncio 并发，max_concurrent=15，连接池复用
图片保存: 异步写盘
```

### 13.3 内存控制

- 流水线队列 maxsize=3，最多同时持有 3 页图片 (~26MB)
- 处理完后立即释放页面对象
- 100 页文档预期内存占用 ~200-600MB

### 13.4 成本控制

- 原生页面直接提取文本：零 VLM 成本
- 同页区域批量合并：请求数可降 33-66%
- VLM 图片 70% 降采样：token 减少约 50%
- 三层缓存：重复处理秒级返回
- dry-run 模式：先估算再执行
- 预算限制：`--max-cost` / `budget_limit_yuan`

---

## 14. 部署方案

### 14.1 开发环境

```bash
# 后端
uv sync
pagetract serve --port 8000

# 快速 Demo (Gradio)
pagetract demo

# 生产级前端 (Vue)
cd frontend
pnpm install
pnpm dev
```

### 14.2 Docker 部署

```yaml
# docker-compose.yml
version: "3.8"
services:
  api:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./config.yaml:/app/config.yaml
      - ./data:/app/data
      - ./cache:/app/cache
    environment:
      - SCANDOC_API_KEY=${SCANDOC_API_KEY}
```

### 14.3 项目目录结构

```
pagetract/
├── src/
│   └── pagetract/
│       ├── __init__.py
│       ├── core/
│       │   ├── input_adapter.py       # 模块I: 输入适配器（新增）
│       │   ├── pdf_detector.py        # 模块Z: PDF 类型检测
│       │   ├── preprocessor.py        # 模块G: 页面预处理
│       │   ├── renderer.py            # 模块A: PDF 渲染器
│       │   ├── native_extractor.py    # 模块A': 原生文本提取
│       │   ├── layout_detector.py     # 模块B: 布局检测
│       │   ├── region_dispatcher.py   # 模块C: 区域分发器
│       │   ├── vlm_engine.py          # 模块D: VLM 引擎
│       │   ├── image_saver.py         # 模块E: 图片保存器
│       │   ├── cross_page_merger.py   # 模块H: 跨页合并
│       │   ├── markdown_assembler.py  # 模块F: Markdown 组装器
│       │   ├── cache.py               # 缓存管理
│       │   ├── pipeline.py            # 流水线编排
│       │   └── prompts.py             # Prompt 管理
│       ├── api/
│       │   ├── __init__.py
│       │   └── app.py
│       ├── demo/
│       │   ├── __init__.py
│       │   └── gradio_app.py
│       ├── cli.py
│       ├── config.py
│       └── models.py
├── tests/
├── docs/
│   ├── requirements-v1.md
│   ├── requirements-v2.md
│   ├── requirements-v2.1.md
│   └── requirements-v3.md
├── config.yaml
├── pyproject.toml
└── README.md
```

---

## 15. 后续扩展方向（非 MVP 范围）

围绕"让大模型读懂一切"的核心使命，后续可扩展：

1. **更多输入格式**：PPT/PPTX、Word/DOCX、HTML 截图、手写笔记照片
2. **MCP Server 集成**：封装为 MCP 工具，AI Agent 可直接调用
3. **批量处理队列**：Celery + Redis
4. **多模型 ensemble**：多 VLM 投票取最佳
5. **增量处理**：仅重新处理修改/新增页面
6. **输出格式扩展**：除 Markdown 外支持 JSON (结构化)、纯文本等 LLM 友好格式
7. **自动分块**：内置 RAG-friendly 的文档分块策略（按标题/语义分块）
8. **多语言 prompt 自适应**：自动检测文档语言，适配 VLM prompt

---

## 16. 验收标准

### 16.1 功能验收

- [ ] 能正确处理纯扫描件 PDF
- [ ] 能正确处理原生数字 PDF（自动提取文本层 + 公式回退到 VLM）
- [ ] 能正确处理混合型 PDF（逐页自适应）
- [ ] 能正确处理学术论文（双栏布局、公式、表格、引用）
- [ ] 能正确处理图片文件输入（JPG/PNG 等）
- [ ] 旋转/倾斜扫描件能自动校正后正确处理
- [ ] 低质量 OCR 文本层能被正确识别为 SCANNED
- [ ] 布局检测能区分 text / image / table / formula / title 类型
- [ ] 多栏布局能正确排序阅读顺序
- [ ] 跨页表格/段落能被检测并合并
- [ ] VLM 输出校验能发现不合理的识别结果
- [ ] 缓存系统正常工作（重复处理可秒级返回）
- [ ] 成本预估（dry-run）可用
- [ ] CLI 所有子命令可用（convert/serve/config/doctor）
- [ ] Python SDK 可用
- [ ] API 服务（含 SSE 进度推送、任务取消）可用
- [ ] Demo 网站可上传、查看进度、逐页对比、下载

### 16.2 输出质量验收（LLM 消费视角）

| 验证项 | 标准 |
|--------|------|
| 语义顺序 | 多栏文档输出顺序与人类阅读顺序一致 |
| 表格完整性 | 表格行列关系正确，LLM 能基于表格回答问题 |
| 公式精度 | LaTeX 公式能被 LLM 正确解析和推理 |
| 图片描述 | alt text 足以让 LLM 理解图片核心内容 |
| 噪声过滤 | 页眉页脚、水印不出现在输出中 |
| 来源可追溯 | 每段内容可追溯到原文页码和区域 |

### 16.3 测试用例

| 用例 | 输入 | 预期输出 |
|------|------|----------|
| 纯文字扫描件 | 只有段落文字的扫描 PDF | 干净的 Markdown 文本 |
| 原生数字 PDF | 有完整文本层的 PDF | 直接提取文本，VLM 调用极少 |
| 有公式的原生 PDF | 含 LaTeX 公式的学术 PDF | 文本提取 + 公式区域回退 VLM |
| 低质量 OCR 层 PDF | 扫描件被 OCR 加了乱码层 | 正确识别为 SCANNED，走 VLM |
| 图文混排 | 含照片和说明文字 | 文字识别 + 图片提取 + 正确引用 |
| 学术论文 | 双栏，含公式/表格/引用 | 正确阅读顺序 + LaTeX + 表格 |
| 旋转扫描件 | 旋转 90° 的扫描 PDF | 自动校正后正确识别 |
| 跨页表格 | 表格跨 2 页 | 合并为一个完整表格 |
| **图片文件** | 拍照的文档页面 (JPG) | 识别文字+表格，生成 Markdown |
| **批量图片** | 多张文档照片 | 按顺序合成完整文档 |
| 加密 PDF | 有密码保护 | 报友好错误提示 |
| 超长页面 | 高度 > 4000px | 自动分割处理 |
| 重复处理 | 同一文件处理两次 | 第二次秒级返回（缓存命中） |
| API 转换 | 通过 API 上传 | SSE 推送进度 + 正确结果 |
| 成本预估 | dry-run 模式 | 返回预估成本和耗时 |

---

## 附录 A：示例输出

### 输入：一页包含标题、正文、图片、表格的学术论文扫描件

### 期望输出 `document.md`：

```markdown
<!-- Page 3 -->

## 3. Experimental Results

<!-- Source: page 3, block 1 -->

We conducted extensive experiments on three benchmark datasets to evaluate
the performance of our proposed method. Table 1 summarizes the key metrics
across all baselines.

<!-- Source: page 3, block 2 -->

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

```bash
# 上传 PDF 并转换
curl -X POST http://localhost:8000/api/v1/convert \
  -F "file=@paper.pdf" \
  -F 'config={"vlm": {"model": "qwen-vl-max"}}'

# 上传图片并转换
curl -X POST http://localhost:8000/api/v1/convert \
  -F "file=@document_photo.jpg"

# SSE 实时进度
curl -N http://localhost:8000/api/v1/tasks/{task_id}/events

# 成本预估
curl -X POST http://localhost:8000/api/v1/estimate \
  -F "file=@paper.pdf"

# 下载结果
curl -O http://localhost:8000/api/v1/files/{task_id}/result.zip
```

```python
from pagetract import PageTract

converter = PageTract(config_path="config.yaml")

# 转换 PDF
result = converter.convert("paper.pdf", output_dir="./output")
print(result.markdown)

# 转换图片
result = converter.convert("document_photo.jpg", output_dir="./output")
print(result.markdown)

# 成本预估
estimate = converter.estimate("paper.pdf")
print(f"页数: {estimate.total_pages}, 预估成本: ¥{estimate.cost_yuan}")
```
