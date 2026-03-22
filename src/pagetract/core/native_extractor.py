"""模块A'：原生文本提取器 — 从 PDF 文本层直接提取结构化内容"""

from __future__ import annotations

import logging
import re
import unicodedata

import fitz  # PyMuPDF

from pagetract.config import NativeExtractConfig
from pagetract.models import (
    EmbeddedImage,
    FallbackRegion,
    NativePageContent,
    NativeTable,
    TextBlock,
)

logger = logging.getLogger(__name__)


class NativeTextExtractor:
    """对 NATIVE / MIXED 页面直接提取 PDF 文本层内容"""

    def __init__(self, config: NativeExtractConfig | None = None):
        self.config = config or NativeExtractConfig()

    def extract(self, doc: fitz.Document, page_idx: int) -> NativePageContent:
        """提取单页原生内容"""
        page = doc[page_idx]
        page_number = page_idx + 1

        text_blocks = self._extract_text_blocks(page)
        embedded_images = self._extract_embedded_images(doc, page)
        tables = self._extract_tables(page)
        fallback_regions = self._detect_fallback_regions(page, text_blocks)

        return NativePageContent(
            page_number=page_number,
            text_blocks=text_blocks,
            embedded_images=embedded_images,
            tables=tables,
            needs_vlm_fallback=fallback_regions,
        )

    # ----------------------------------------------------------
    # 文本提取
    # ----------------------------------------------------------

    def _extract_text_blocks(self, page: fitz.Page) -> list[TextBlock]:
        blocks: list[TextBlock] = []
        text_dict = page.get_text("dict")

        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:  # 非文本块
                continue
            bbox = tuple(int(v) for v in block["bbox"])

            for line in block.get("lines", []):
                line_text = ""
                font_size = 12.0
                font_name = ""
                is_bold = False
                is_italic = False

                for span in line.get("spans", []):
                    line_text += span.get("text", "")
                    font_size = span.get("size", 12.0)
                    font_name = span.get("font", "")
                    flags = span.get("flags", 0)
                    is_bold = is_bold or bool(flags & 2 ** 4)
                    is_italic = is_italic or bool(flags & 2 ** 1)

                if line_text.strip():
                    line_bbox = tuple(int(v) for v in line["bbox"])
                    blocks.append(TextBlock(
                        text=line_text.strip(),
                        bbox=line_bbox,  # type: ignore[arg-type]
                        font_size=font_size,
                        font_name=font_name,
                        is_bold=is_bold,
                        is_italic=is_italic,
                    ))

        return blocks

    # ----------------------------------------------------------
    # 嵌入图片提取
    # ----------------------------------------------------------

    def _extract_embedded_images(
        self, doc: fitz.Document, page: fitz.Page
    ) -> list[EmbeddedImage]:
        from PIL import Image
        import io

        images: list[EmbeddedImage] = []
        image_list = page.get_images(full=True)

        for img_info in image_list:
            xref = img_info[0]
            try:
                base_image = doc.extract_image(xref)
                if not base_image:
                    continue
                img_bytes = base_image["image"]
                pil_img = Image.open(io.BytesIO(img_bytes))

                # 获取图片在页面上的位置
                rects = page.get_image_rects(xref)
                for rect in rects:
                    bbox = (int(rect.x0), int(rect.y0), int(rect.x1), int(rect.y1))
                    images.append(EmbeddedImage(
                        image=pil_img.copy(),
                        bbox=bbox,
                        xref=xref,
                    ))
            except Exception as e:
                logger.warning("Failed to extract image xref=%d: %s", xref, e)

        return images

    # ----------------------------------------------------------
    # 表格提取（简易版）
    # ----------------------------------------------------------

    def _extract_tables(self, page: fitz.Page) -> list[NativeTable] | None:
        try:
            tabs = page.find_tables()
            if not tabs or not tabs.tables:
                return None

            result: list[NativeTable] = []
            for table in tabs.tables:
                bbox = tuple(int(v) for v in table.bbox)
                cells: list[list[str]] = []
                extracted = table.extract()
                for row in extracted:
                    cells.append([str(cell) if cell else "" for cell in row])
                result.append(NativeTable(bbox=bbox, cells=cells))  # type: ignore[arg-type]
            return result
        except Exception as e:
            logger.debug("Table extraction not available: %s", e)
            return None

    # ----------------------------------------------------------
    # 回退区域检测
    # ----------------------------------------------------------

    def _detect_fallback_regions(
        self, page: fitz.Page, text_blocks: list[TextBlock]
    ) -> list[FallbackRegion]:
        if not self.config.fallback_to_vlm:
            return []

        fallbacks: list[FallbackRegion] = []

        # 1. 检测公式字体区域
        text_dict = page.get_text("dict")
        for block in text_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    font = span.get("font", "")
                    for pattern in self.config.formula_font_patterns:
                        if pattern.lower() in font.lower():
                            bbox = tuple(int(v) for v in block["bbox"])
                            fallbacks.append(FallbackRegion(
                                bbox=bbox,  # type: ignore[arg-type]
                                reason="formula",
                            ))
                            break

        # 2. 检测乱码区域
        for tb in text_blocks:
            garbled_count = sum(
                1 for c in tb.text
                if unicodedata.category(c) in ("Co", "Cn")
            )
            if len(tb.text) > 0 and garbled_count / len(tb.text) > self.config.garbled_text_threshold:
                fallbacks.append(FallbackRegion(
                    bbox=tb.bbox,
                    reason="garbled_text",
                ))

        # 去重合并（重叠区域只保留一个）
        return self._deduplicate_regions(fallbacks)

    @staticmethod
    def _deduplicate_regions(regions: list[FallbackRegion]) -> list[FallbackRegion]:
        if len(regions) <= 1:
            return regions
        seen_bboxes: set[tuple[int, int, int, int]] = set()
        unique: list[FallbackRegion] = []
        for r in regions:
            if r.bbox not in seen_bboxes:
                seen_bboxes.add(r.bbox)
                unique.append(r)
        return unique
