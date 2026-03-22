"""Prompt 模板管理"""

from __future__ import annotations

from pagetract.models import BlockType

# ============================================================
# 默认 Prompt 模板
# ============================================================

PROMPTS: dict[str, str] = {
    "text": (
        "你是一个专业的 OCR 系统。图片是一个完整的文档页面。\n"
        "请精确识别坐标区域 ({x1}, {y1}) 到 ({x2}, {y2}) 范围内的所有文字内容。\n"
        "坐标以像素为单位，左上角为原点。\n"
        "要求：\n"
        "- 只识别指定坐标区域内的文字，忽略区域外的内容\n"
        "- 逐字精确，不要遗漏或添加任何内容\n"
        "- 保留原文的段落结构\n"
        "- 如果有加粗、斜体等格式，用 Markdown 语法标记\n"
        "- 不要输出任何解释性文字，只输出识别结果"
    ),
    "title": (
        "请识别图片中坐标区域 ({x1}, {y1}) 到 ({x2}, {y2}) 范围内的标题文字。\n"
        "只输出标题文本，不添加任何其他内容。"
    ),
    "table": (
        "请将图片中坐标区域 ({x1}, {y1}) 到 ({x2}, {y2}) 范围内的表格\n"
        "精确转换为 Markdown 表格格式。\n"
        "要求：\n"
        "- 只关注指定坐标区域内的表格\n"
        "- 表头用 | --- | 分隔\n"
        "- 保持行列结构完全一致\n"
        "- 如果表格过于复杂无法用 Markdown 表示，请使用 HTML <table> 标签\n"
        "- 不要输出任何解释性文字"
    ),
    "formula": (
        "请将图片中坐标区域 ({x1}, {y1}) 到 ({x2}, {y2}) 范围内的数学公式\n"
        "转换为 LaTeX 格式。\n"
        "要求：\n"
        "- 只关注指定坐标区域内的公式\n"
        "- 用 $$ $$ 包裹行间公式\n"
        "- 精确还原所有数学符号、上下标、分数、积分等\n"
        "- 不要输出任何解释性文字，只输出 LaTeX 代码"
    ),
    "caption": (
        "请识别图片中坐标区域 ({x1}, {y1}) 到 ({x2}, {y2}) 范围内的说明文字。\n"
        "只输出文本内容。"
    ),
    "image_alt": (
        "请观察图片中坐标区域 ({x1}, {y1}) 到 ({x2}, {y2}) 范围内的图片内容，\n"
        "用一句简洁的描述，用于 Markdown 的 alt text。不要超过 50 个字。"
    ),
    "list": (
        "请识别图片中坐标区域 ({x1}, {y1}) 到 ({x2}, {y2}) 范围内的列表内容。\n"
        "要求：\n"
        "- 使用 Markdown 列表格式 (- 或 1. 2. 3.)\n"
        "- 保持列表的层级结构\n"
        "- 不要输出任何解释性文字"
    ),
    "code": (
        "请识别图片中坐标区域 ({x1}, {y1}) 到 ({x2}, {y2}) 范围内的代码内容。\n"
        "要求：\n"
        "- 保持代码缩进和格式\n"
        "- 尝试识别编程语言\n"
        "- 不要输出任何解释性文字"
    ),
    "reference": (
        "请识别图片中坐标区域 ({x1}, {y1}) 到 ({x2}, {y2}) 范围内的参考文献。\n"
        "保持原始格式和编号。"
    ),
    "batch": (
        "你是一个专业的 OCR 系统。图片是一个完整的文档页面。\n"
        "请依次识别以下各坐标区域的内容，每个区域的结果用 [REGION_N] 标记分隔：\n"
        "{regions_description}\n"
        "要求：\n"
        "- 对每个区域，只识别该坐标范围内的内容\n"
        "- 逐字精确，保留格式\n"
        "- 用 [REGION_1], [REGION_2], ... 标记各区域结果的开头"
    ),
    "full_page": (
        "你是一个专业的 OCR 系统。请识别图片中的所有文字内容。\n"
        "要求：\n"
        "- 逐字精确，保留原文格式和段落结构\n"
        "- 如果有标题，用 Markdown 标题语法\n"
        "- 如果有表格，转为 Markdown 表格\n"
        "- 如果有公式，转为 LaTeX\n"
        "- 不要输出任何解释性文字"
    ),
}

# BlockType → prompt key 映射
BLOCK_PROMPT_MAP: dict[BlockType, str] = {
    BlockType.TEXT: "text",
    BlockType.TITLE: "title",
    BlockType.TABLE: "table",
    BlockType.FORMULA: "formula",
    BlockType.CAPTION: "caption",
    BlockType.IMAGE: "image_alt",
    BlockType.LIST: "list",
    BlockType.CODE: "code",
    BlockType.REFERENCE: "reference",
}


def get_prompt(
    block_type: BlockType,
    bbox: tuple[int, int, int, int],
    custom_prompts: dict[str, str] | None = None,
) -> str:
    """获取格式化后的 prompt"""
    key = BLOCK_PROMPT_MAP.get(block_type, "text")

    # 自定义 prompt 优先
    if custom_prompts and key in custom_prompts:
        template = custom_prompts[key]
    else:
        template = PROMPTS[key]

    return template.format(x1=bbox[0], y1=bbox[1], x2=bbox[2], y2=bbox[3])


def get_batch_prompt(
    regions: list[tuple[tuple[int, int, int, int], BlockType]],
    custom_prompts: dict[str, str] | None = None,
) -> str:
    """获取批量识别 prompt"""
    descriptions: list[str] = []
    for i, (bbox, block_type) in enumerate(regions, 1):
        type_label = block_type.value
        descriptions.append(
            f"[REGION_{i}] 类型={type_label}, 坐标=({bbox[0]}, {bbox[1]}) 到 ({bbox[2]}, {bbox[3]})"
        )

    regions_text = "\n".join(descriptions)

    if custom_prompts and "batch" in custom_prompts:
        template = custom_prompts["batch"]
    else:
        template = PROMPTS["batch"]

    return template.format(regions_description=regions_text)
