"""模块F：Markdown 组装器 — 按阅读顺序拼装最终 Markdown"""

from __future__ import annotations

import logging
from pathlib import Path

from pagetract.config import MarkdownConfig
from pagetract.models import BlockType, ProcessedBlock

logger = logging.getLogger(__name__)


class MarkdownAssembler:
    """按阅读顺序将所有处理结果拼装为 Markdown 文件"""

    def __init__(self, config: MarkdownConfig | None = None):
        self.config = config or MarkdownConfig()
        self._title_sizes: list[float] = []  # 用于推断标题层级

    def assemble(
        self,
        blocks: list[ProcessedBlock],
        output_dir: str | Path | None = None,
    ) -> str:
        """拼装所有 block 为 Markdown 文本"""
        # 排序
        blocks = sorted(blocks, key=lambda b: (b.page_number, b.reading_order))

        # 收集标题字号用于层级推断
        self._collect_title_info(blocks)

        parts: list[str] = []
        current_page = 0
        references: list[ProcessedBlock] = []

        for block in blocks:
            # 参考文献收集到末尾
            if block.block_type == BlockType.REFERENCE:
                references.append(block)
                continue

            # 丢弃 header/footer
            if self.config.discard_header_footer:
                if block.block_type in (BlockType.HEADER, BlockType.FOOTER, BlockType.PAGE_NUMBER):
                    continue

            # 页间分隔
            if block.page_number != current_page:
                if current_page > 0:
                    parts.append(self.config.page_separator)
                current_page = block.page_number
                if self.config.include_page_markers:
                    parts.append(f"<!-- Page {current_page} -->\n\n")

            # 转换为 Markdown
            md = self._block_to_markdown(block)
            if md:
                if self.config.include_source_markers:
                    parts.append(
                        f"<!-- Source: page {block.page_number}, "
                        f"block {block.reading_order} -->\n"
                    )
                parts.append(md)
                parts.append("\n\n")

        # 参考文献区
        if references:
            parts.append("\n\n## References\n\n")
            for ref in references:
                parts.append(ref.content)
                parts.append("\n\n")

        markdown = "".join(parts).rstrip() + "\n"

        # 保存到文件
        if output_dir:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            md_path = output_dir / "document.md"
            md_path.write_text(markdown, encoding="utf-8")
            logger.info("Markdown saved to %s", md_path)

        return markdown

    # ----------------------------------------------------------
    # Block → Markdown 转换
    # ----------------------------------------------------------

    def _block_to_markdown(self, block: ProcessedBlock) -> str:
        content = block.content.strip()
        if not content:
            if block.image_path:
                return f"![](images/{Path(block.image_path).name})"
            return ""

        btype = block.block_type

        if btype == BlockType.TITLE:
            level = self._infer_title_level(block)
            prefix = "#" * level
            return f"{prefix} {content}"

        if btype == BlockType.TEXT:
            return content

        if btype == BlockType.IMAGE:
            alt = content if content else "image"
            if block.image_path:
                return f"![{alt}]({block.image_path})"
            return f"![{alt}]()"

        if btype == BlockType.TABLE:
            return content  # 已经是 Markdown 表格

        if btype == BlockType.FORMULA:
            # 确保有 $$ 包裹
            if not content.startswith("$$"):
                content = f"$$\n{content}\n$$"
            return content

        if btype == BlockType.CAPTION:
            return f"*{content}*"

        if btype == BlockType.LIST:
            return content

        if btype == BlockType.CODE:
            if not content.startswith("```"):
                content = f"```\n{content}\n```"
            return content

        return content

    # ----------------------------------------------------------
    # 标题层级推断
    # ----------------------------------------------------------

    def _collect_title_info(self, blocks: list[ProcessedBlock]) -> None:
        """收集所有标题的字号信息"""
        self._title_sizes = []
        for b in blocks:
            if b.block_type == BlockType.TITLE:
                # 从字号推断层级 (用 bbox 高度近似)
                height = b.bbox[3] - b.bbox[1]
                self._title_sizes.append(height)

    def _infer_title_level(self, block: ProcessedBlock) -> int:
        """推断标题的 Markdown 层级 (1-4)"""
        if self.config.title_level_strategy == "flat":
            return 2

        if not self._title_sizes:
            return 1

        height = block.bbox[3] - block.bbox[1]
        max_h = max(self._title_sizes) if self._title_sizes else height
        min_h = min(self._title_sizes) if self._title_sizes else height

        if max_h == min_h:
            return 2

        # 归一化到 1-4
        ratio = (height - min_h) / (max_h - min_h) if max_h > min_h else 0.5
        if ratio > 0.75:
            return 1
        if ratio > 0.5:
            return 2
        if ratio > 0.25:
            return 3
        return 4
