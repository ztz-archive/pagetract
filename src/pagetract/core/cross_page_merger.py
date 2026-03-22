"""模块H：跨页元素合并器 — 检测并合并跨页表格、段落等"""

from __future__ import annotations

import logging
import re

from pagetract.models import BlockType, CrossPagePair, ProcessedBlock

logger = logging.getLogger(__name__)


class CrossPageAggregator:
    """检测并合并跨页表格、跨页段落等连续元素"""

    def __init__(self, page_heights: dict[int, int] | None = None):
        self._page_heights = page_heights or {}

    def detect_and_merge(
        self,
        all_blocks: list[ProcessedBlock],
    ) -> list[ProcessedBlock]:
        """检测跨页元素并合并，返回合并后的 block 列表"""
        if len(all_blocks) < 2:
            return all_blocks

        pairs = self._detect_cross_page_pairs(all_blocks)
        if not pairs:
            return all_blocks

        logger.info("Detected %d cross-page pairs", len(pairs))

        # 执行合并
        merged_indices: set[int] = set()
        result: list[ProcessedBlock] = []

        block_index = {id(b): i for i, b in enumerate(all_blocks)}

        for pair in pairs:
            idx1 = block_index.get(id(pair.block1))
            idx2 = block_index.get(id(pair.block2))
            if idx1 is None or idx2 is None:
                continue

            merged = self._merge_pair(pair)
            merged_indices.add(idx1)
            merged_indices.add(idx2)
            result.append(merged)

        # 添加未合并的 block
        for i, block in enumerate(all_blocks):
            if i not in merged_indices:
                result.append(block)

        # 按页码和阅读顺序排序
        result.sort(key=lambda b: (b.page_number, b.reading_order))
        return result

    # ----------------------------------------------------------
    # 检测跨页配对
    # ----------------------------------------------------------

    def _detect_cross_page_pairs(
        self, all_blocks: list[ProcessedBlock]
    ) -> list[CrossPagePair]:
        # 按页分组
        pages: dict[int, list[ProcessedBlock]] = {}
        for b in all_blocks:
            pages.setdefault(b.page_number, []).append(b)

        page_nums = sorted(pages.keys())
        pairs: list[CrossPagePair] = []

        for i in range(len(page_nums) - 1):
            pn1 = page_nums[i]
            pn2 = page_nums[i + 1]
            if pn2 - pn1 != 1:
                continue

            blocks1 = pages[pn1]
            blocks2 = pages[pn2]

            page_h = self._page_heights.get(pn1, 3000)

            # 页面底部的 block
            bottom_blocks = [
                b for b in blocks1
                if b.bbox[3] > page_h * 0.90
            ]
            # 下一页顶部的 block
            top_blocks = [
                b for b in blocks2
                if b.bbox[1] < page_h * 0.10
            ]

            for b1 in bottom_blocks:
                for b2 in top_blocks:
                    if b1.block_type == b2.block_type:
                        merge_type = self._classify_merge(b1, b2)
                        if merge_type:
                            pairs.append(CrossPagePair(
                                block1=b1, block2=b2,
                                merge_type=merge_type,
                            ))

        return pairs

    def _classify_merge(self, b1: ProcessedBlock, b2: ProcessedBlock) -> str | None:
        """判断是否可以合并，返回合并类型"""
        if b1.block_type == BlockType.TABLE:
            # 表格需要列数匹配
            if self._table_columns_match(b1.content, b2.content):
                return "table"
        elif b1.block_type == BlockType.TEXT:
            # 文本段落：检查连续性（末尾非句号）
            stripped = b1.content.rstrip()
            if stripped and stripped[-1] not in ".。!！?？":
                return "paragraph"
        elif b1.block_type == BlockType.FORMULA:
            return "formula"
        return None

    # ----------------------------------------------------------
    # 合并执行
    # ----------------------------------------------------------

    def _merge_pair(self, pair: CrossPagePair) -> ProcessedBlock:
        """执行合并"""
        b1, b2 = pair.block1, pair.block2

        if pair.merge_type == "table":
            content = self._merge_tables(b1.content, b2.content)
        elif pair.merge_type == "paragraph":
            content = b1.content.rstrip() + " " + b2.content.lstrip()
        elif pair.merge_type == "formula":
            content = b1.content.rstrip() + "\n" + b2.content.lstrip()
        else:
            content = b1.content + "\n" + b2.content

        return ProcessedBlock(
            block_type=b1.block_type,
            bbox=b1.bbox,
            page_number=b1.page_number,
            reading_order=b1.reading_order,
            content=content,
            content_type=b1.content_type,
            source=b1.source,
        )

    # ----------------------------------------------------------
    # 表格合并
    # ----------------------------------------------------------

    @staticmethod
    def _merge_tables(table1: str, table2: str) -> str:
        """合并两个 Markdown 表格（去重复表头）"""
        lines1 = [l for l in table1.strip().split("\n") if l.strip()]
        lines2 = [l for l in table2.strip().split("\n") if l.strip()]

        if not lines2:
            return table1

        # 检查 table2 是否有表头（第二行为 |---|）
        has_header = len(lines2) > 1 and re.match(r"^\|[\s\-|:]+\|$", lines2[1])
        if has_header and len(lines2) > 2:
            # 跳过表头和分隔线
            data_lines = lines2[2:]
        else:
            data_lines = lines2

        return "\n".join(lines1 + data_lines)

    @staticmethod
    def _table_columns_match(table1: str, table2: str) -> bool:
        """检查两个表格列数是否匹配"""
        lines1 = table1.strip().split("\n")
        lines2 = table2.strip().split("\n")

        def count_cols(line: str) -> int:
            return line.count("|") - 1

        if lines1 and lines2:
            return count_cols(lines1[0]) == count_cols(lines2[0])
        return False
