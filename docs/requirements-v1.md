# pagetract — 基于混合架构的高精度扫描件文档转 Markdown 系统

## 项目需求文档 v1.0

---

## 1. 项目概述

### 1.1 项目定位

pagetract 是一个开源的文档处理工具，专注于将**扫描件 PDF**（整页都是图片、无文本层）高精度地转换为带图片引用的结构化 Markdown 文档。

### 1.2 核心设计理念

采用**"CV 切分 + LLM 精识别"的混合架构**：

- **布局检测**交给专用 CV 模型（快、准、稳），负责定位和分类页面中的各区域
- **内容识别**交给大参数量视觉 LLM（如 Qwen3.5-plus、GPT-4o 等），追求极致 OCR 精度
- **图片提取**由 CV 工具按坐标裁剪，保留原始图片质量
- 各模块各司其职，通过标准化的中间数据格式解耦

### 1.3 目标用户场景

- 学术研究者：将扫描版论文、书籍章节转为可编辑的 Markdown
- 文档数字化：将历史扫描档案转为结构化文本
- RAG 数据准备：为大模型知识库准备高质量文档数据

### 1.4 与同类项目的差异

| 对比项 | MinerU | Zerox / gptpdf | pagetract |
|--------|--------|----------------|------------|
| 布局检测 | 自带 DocLayout-YOLO | 无 | 可插拔 CV 模型 |
| OCR 引擎 | 自带小模型 / VLM | 全靠 VLM | 大参数 VLM（可配置） |
| 图片提取 | ✅ 支持 | ❌ 不支持 | ✅ 支持 |
| 扫描件支持 | ✅ | 有限（无图片提取） | ✅ 专门优化 |
| VLM 可替换 | 仅限自带模型 + llm-aided | 支持多 provider | 完全可插拔 |
| 部署复杂度 | 高（需要多个模型） | 低 | 中等 |

---

## 2. 系统架构

### 2.1 整体流程

```
输入: 扫描件 PDF
  │
  ▼
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
  │
  ├── text 区域 ──→ [模块D] VLM OCR 引擎 ──→ 识别后的文本
  ├── title 区域 ──→ [模块D] VLM OCR 引擎 ──→ 识别后的标题文本 (带层级)
  ├── image 区域 ──→ [模块E] 图片裁剪器 ──→ 保存为独立图片文件
  ├── table 区域 ──→ [模块D] VLM OCR 引擎 ──→ Markdown/HTML 表格
  ├── formula 区域 ──→ [模块D] VLM OCR 引擎 ──→ LaTeX 公式
  └── header/footer ──→ 可选保留或丢弃
  │
  ▼
[模块F] Markdown 组装器
  │  按阅读顺序拼装所有识别结果
  │  图片引用为相对路径 ![](images/page1_fig1.png)
  ▼
输出: 结构化 Markdown 文件 + images/ 目录
```

### 2.2 目录结构约定

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

### 3.1 模块A：PDF 页面渲染器

**职责**：将 PDF 每页渲染为高分辨率位图。

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
- 对于原生 PDF（有文本层的），也应走同样的渲染流程以保持一致性；但可以额外提取文本层用于后续校验

---

### 3.2 模块B：布局检测引擎

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

### 3.3 模块C：区域处理分发器

**职责**：根据区域类型分发到不同的处理器。

**核心逻辑**：

```
对每个 LayoutBlock:
    if block_type in [TITLE, TEXT, CAPTION, LIST, REFERENCE, CODE]:
        → 裁剪区域图片 → 送 VLM OCR 引擎识别文字
    elif block_type == IMAGE:
        → 裁剪区域图片 → 直接保存为文件
        → (可选) 同时送 VLM 生成图片描述作为 alt text
    elif block_type == TABLE:
        → 裁剪区域图片 → 送 VLM 识别为 Markdown 表格或 HTML
        → 同时保存表格区域图片作为备份
    elif block_type == FORMULA:
        → 裁剪区域图片 → 送 VLM 识别为 LaTeX
    elif block_type in discard_types:
        → 跳过
```

**区域裁剪时的边距处理**：

裁剪时应在 bbox 基础上向外扩展少量 padding（如 5-10px），避免文字紧贴边界导致识别率下降。但扩展不能超出页面边界。

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

### 3.4 模块D：VLM OCR 引擎

**职责**：调用大参数量视觉 LLM 对区域图片进行高精度内容识别。

**设计要求**：
- 通过 OpenAI 兼容 API 接口统一接入，支持任意 VLM provider
- 不同区域类型使用不同的 system prompt
- 支持并发请求以提升吞吐
- 支持重试和错误处理

**抽象接口**：

```python
class VLMEngine(Protocol):
    async def recognize(
        self,
        image: PIL.Image.Image,
        block_type: BlockType,
        context: str | None = None  # 可选的上下文信息，如"这是一篇关于xxx的学术论文"
    ) -> RecognitionResult:
        ...

@dataclass
class RecognitionResult:
    content: str               # 识别出的文本/LaTeX/Markdown表格
    content_type: str          # "text" | "latex" | "markdown_table" | "html_table"
    confidence: float | None   # 模型自评置信度（如果模型支持）
    raw_response: str          # 原始模型输出（用于调试）
```

**各区域类型的 Prompt 策略**：

```yaml
text_prompt: |
  你是一个专业的 OCR 系统。请精确识别图片中的所有文字内容。
  要求：
  - 逐字精确，不要遗漏或添加任何内容
  - 保留原文的段落结构
  - 如果有加粗、斜体等格式，用 Markdown 语法标记
  - 不要输出任何解释性文字，只输出识别结果

title_prompt: |
  请识别图片中的标题文字。只输出标题文本，不添加任何其他内容。

table_prompt: |
  请将图片中的表格精确转换为 Markdown 表格格式。
  要求：
  - 表头用 | --- | 分隔
  - 保持行列结构完全一致
  - 单元格内容精确识别
  - 如果表格过于复杂无法用 Markdown 表示，请使用 HTML <table> 标签
  - 不要输出任何解释性文字

formula_prompt: |
  请将图片中的数学公式转换为 LaTeX 格式。
  要求：
  - 用 $$ $$ 包裹行间公式
  - 精确还原所有数学符号、上下标、分数、积分等
  - 不要输出任何解释性文字，只输出 LaTeX 代码

caption_prompt: |
  请识别图片中的说明文字（图标题或表标题）。只输出文本内容。

image_alt_prompt: |
  请用一句简洁的中文描述这张图片的内容，用于 Markdown 的 alt text。
  不要超过 50 个字。
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

### 3.5 模块E：图片裁剪器

**职责**：将检测为 image 类型的区域从页面图片中裁剪出来，保存为独立文件。

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

**配置项**：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `image_format` | str | "png" | 保存格式 |
| `image_quality` | int | 95 | JPEG 质量（仅 jpg 格式时生效） |
| `min_image_size` | int | 50 | 宽或高小于此值(px)的图片区域忽略（可能是噪点） |
| `padding` | int | 5 | 裁剪时的外扩像素数 |
| `save_table_images` | bool | True | 是否同时将表格区域保存为图片备份 |

---

### 3.6 模块F：Markdown 组装器

**职责**：按阅读顺序将所有处理结果拼装为最终 Markdown 文件。

**组装规则**：

```
1. 按 page_number 排序，同页内按 reading_order 排序
2. 页与页之间插入分页标记（可配置）
3. 不同类型的内容使用不同的 Markdown 语法：
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

## 4. 配置系统设计

### 4.1 统一配置文件

使用单一 YAML 文件 `config.yaml` 管理所有配置：

```yaml
# pagetract 配置文件

# 全局设置
general:
  render_dpi: 300
  page_range: null          # null 表示处理所有页, 或 [1, 2, 5] 指定页码
  output_dir: "./output"
  document_context: ""      # 可填写如 "这是一篇关于深度学习的学术论文"

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
  generate_image_alt: true
  custom_prompts: {}        # 可覆盖默认 prompt

# 图片提取
image_extraction:
  format: "png"
  min_size: 50
  padding: 5
  save_table_images: true

# Markdown 输出
markdown:
  page_separator: "\n\n---\n\n"
  include_page_markers: false
  image_ref_style: "relative"
  title_level_strategy: "auto"
```

### 4.2 环境变量

| 环境变量 | 说明 |
|----------|------|
| `SCANDOC_API_KEY` | VLM API 密钥 |
| `SCANDOC_CONFIG` | 配置文件路径（默认 `./config.yaml`） |

---

## 5. CLI 接口设计

### 5.1 基本用法

```bash
# 最简用法
pagetract input.pdf -o output/

# 指定配置文件
pagetract input.pdf -o output/ --config my_config.yaml

# 命令行覆盖参数
pagetract input.pdf -o output/ \
  --model qwen-vl-max \
  --api-key sk-xxx \
  --dpi 400 \
  --pages 1,2,3,5-10

# 批量处理目录下所有 PDF
pagetract ./pdfs/ -o output/ --batch

# 仅做布局检测（调试用，不调用 VLM）
pagetract input.pdf -o output/ --layout-only

# 仅处理指定类型的区域
pagetract input.pdf -o output/ --only-types text,table,image
```

### 5.2 输出示例

```
Processing: input.pdf
  [1/12] Page 1: 8 blocks detected (3 text, 2 image, 1 table, 1 title, 1 caption)
  [2/12] Page 2: 5 blocks detected (4 text, 1 formula)
  ...
  [12/12] Page 12: 6 blocks detected (3 text, 2 reference, 1 footer)

Results:
  Output:     output/document.md
  Images:     output/images/ (7 files)
  Total time: 45.2s
  API calls:  89
  Est. cost:  ¥0.42

Done.
```

---

## 6. Python SDK 接口设计

### 6.1 主入口

```python
from pagetract import pagetract

converter = pagetract(
    config_path="config.yaml"  # 或直接传 dict
)

# 同步接口
result = converter.convert("input.pdf", output_dir="./output")
print(result.markdown)          # Markdown 文本
print(result.images)            # 提取的图片列表
print(result.metadata)          # 处理元数据

# 异步接口
result = await converter.aconvert("input.pdf", output_dir="./output")
```

### 6.2 逐模块调用（高级用法）

```python
from pagetract import PDFRenderer, LayoutDetector, VLMEngine, MarkdownAssembler

# Step 1: 渲染
renderer = PDFRenderer(dpi=300)
pages = renderer.render("input.pdf")

# Step 2: 布局检测
detector = LayoutDetector(engine="doclayout-yolo")
all_blocks = []
for page in pages:
    blocks = detector.detect(page.image)
    all_blocks.extend(blocks)

# Step 3: VLM 识别 + 图片提取
vlm = VLMEngine(provider="dashscope", model="qwen-vl-max")
processed = await vlm.process_blocks(all_blocks, pages)

# Step 4: 组装
assembler = MarkdownAssembler()
markdown = assembler.assemble(processed, output_dir="./output")
```

---

## 7. 技术栈

### 7.1 核心依赖

| 组件 | 推荐库 | 用途 |
|------|--------|------|
| PDF 渲染 | `PyMuPDF (fitz)` | PDF 页面转图片 |
| 布局检测 | `DocLayout-YOLO` / `ultralytics` | 区域检测和分类 |
| 图片处理 | `Pillow` | 裁剪、保存、格式转换 |
| VLM 调用 | `httpx` (async) 或 `openai` SDK | 异步 HTTP 请求 |
| 配置管理 | `pydantic` + `PyYAML` | 配置校验和加载 |
| CLI | `typer` 或 `click` | 命令行接口 |
| 进度显示 | `rich` | 进度条和美化输出 |
| 并发控制 | `asyncio` + `asyncio.Semaphore` | 控制 VLM 并发数 |

### 7.2 开发环境

- Python >= 3.10
- 包管理：`uv` 或 `pip`
- 格式化：`ruff`
- 类型检查：`pyright` 或 `mypy`

---

## 8. 关键设计决策与权衡

### 8.1 为什么不让 VLM 做布局检测？

虽然大模型（如 Qwen3-VL）支持 grounding 输出坐标，但：

- **精度**：专用 YOLO 模型在布局检测上的 mAP 达 97.5%，VLM grounding 远不及
- **成本**：每页都调用大模型做布局检测太贵
- **速度**：YOLO 毫秒级，VLM 秒级
- **确定性**：CV 模型输出稳定，VLM 可能每次结果不同

结论：布局检测给 CV 模型，内容理解给 VLM。

### 8.2 为什么逐区域送 VLM 而不是整页送？

- 逐区域送可以**使用专门的 prompt**，表格/公式/正文各有优化
- 裁剪后的区域图片分辨率更高（相对于内容面积），**细节识别更准**
- 如果某个区域识别失败，可以**单独重试**，不影响整页其他区域
- 但代价是 API 调用次数更多；通过并发控制和合并小区域来缓解

### 8.3 整页送 VLM 作为 fallback

对于布局极其简单的页面（如只有一块纯文字），可以跳过逐区域切分，直接整页送 VLM 识别，减少 API 调用次数。判断条件：

```python
if len(blocks) <= 2 and all(b.block_type == BlockType.TEXT for b in blocks):
    # 简单页面，整页送 VLM
    result = await vlm.recognize(page_image, BlockType.TEXT)
else:
    # 复杂页面，逐区域处理
    ...
```

### 8.4 图片描述的 alt text 策略

提取的图片需要 alt text，有两种策略：

- **VLM 生成描述**：额外调用 VLM 对裁剪出的图片生成简短描述 → 效果好但多一次 API 调用
- **使用相邻 caption**：如果布局检测到了 caption 区域，且与 image 区域相邻，直接用 caption 文本作为 alt text → 零额外成本

推荐：**优先使用 caption，无 caption 时再调用 VLM 生成。**

---

## 9. 错误处理与鲁棒性

### 9.1 VLM 调用失败

- 单次超时 → 自动重试（最多 max_retries 次）
- 连续失败 → 记录到 metadata.json 中的 errors 字段，跳过该区域，在 Markdown 中插入占位符 `[OCR_FAILED: page X, block Y]`
- 速率限制 → 指数退避重试

### 9.2 布局检测异常

- 某页检测不到任何区域 → 回退到整页送 VLM
- 区域严重重叠 → NMS (非极大抑制) 去重
- 区域超出页面边界 → 裁剪到页面边界内

### 9.3 输入校验

- 非 PDF 文件 → 报错提示
- 空白页 → 跳过，日志记录
- 加密 PDF → 报错提示需要先解密
- 超大文件 (>1000页) → 警告并建议分批处理

---

## 10. 性能优化

### 10.1 并发策略

```
PDF 渲染: 同步顺序处理（IO密集但很快）
布局检测: 可并行（如果 GPU 显存够）
VLM 调用: asyncio 并发，受 max_concurrent 限制
图片保存: 异步写盘
```

### 10.2 成本控制

- 小区域合并：相邻的小 text 区域合并为一块再送 VLM，减少调用次数
- 简单页面整页识别：见 8.3
- token 估算：根据区域面积预估 token 消耗，在处理前给出成本预估
- dry-run 模式：`--dry-run` 只做布局检测和成本预估，不调用 VLM

---

## 11. 后续扩展方向（非 MVP 范围）

以下功能不在首版实现范围内，但架构设计时需要预留扩展点：

1. **Web UI**：基于 Gradio 或 Streamlit 的可视化界面，可预览布局检测结果
2. **MCP Server 集成**：将 pagetract 封装为 MCP 工具，供 Claude Code 等 AI agent 调用
3. **批量处理队列**：支持大规模文档处理的任务队列系统
4. **多模型 ensemble**：同一区域用多个 VLM 识别后投票/对比取最佳
5. **增量处理**：对已处理过的 PDF 只重新处理修改/新增页面
6. **原生 PDF 文本层校验**：对有文本层的 PDF，用 VLM OCR 结果与文本层对比，自动修正乱码
7. **自定义布局检测模型训练**：提供 fine-tuning 接口，用户可在自己的文档类型上训练布局模型

---

## 12. 验收标准

### 12.1 功能验收

- [ ] 能正确处理纯扫描件 PDF（每页一张大图，无文本层）
- [ ] 布局检测能区分 text / image / table / formula / title 类型
- [ ] 文字区域通过 VLM 识别，输出准确的文本
- [ ] 图片区域被裁剪并保存为独立文件，Markdown 中有正确的引用路径
- [ ] 表格区域被识别为 Markdown/HTML 表格
- [ ] 公式区域被识别为 LaTeX
- [ ] 最终输出的 Markdown 文件结构合理、可读
- [ ] 支持通过配置文件切换不同的 VLM provider
- [ ] CLI 和 Python SDK 均可用

### 12.2 测试用例

| 用例 | 输入 | 预期输出 |
|------|------|----------|
| 纯文字扫描件 | 只有段落文字的 PDF | 干净的 Markdown 文本 |
| 图文混排 | 含照片和说明文字的扫描件 | 文字被识别 + 图片被提取保存 |
| 学术论文 | 含公式、表格、引用的论文扫描件 | LaTeX 公式 + Markdown 表格 + 参考文献 |
| 多栏布局 | 双栏排版的论文扫描件 | 正确的阅读顺序，不混淆左右栏 |
| 低质量扫描 | 模糊/倾斜的扫描件 | 尽力识别 + 错误区域有 fallback 标记 |

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