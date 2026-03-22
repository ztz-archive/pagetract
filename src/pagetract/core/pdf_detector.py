"""模块Z：PDF 类型检测器 — 逐页判断 PDF 类型，决定处理策略"""

from __future__ import annotations

import logging
import re
import unicodedata

import fitz  # PyMuPDF

from pagetract.config import PDFDetectionConfig
from pagetract.models import (
    PageClassification,
    PageType,
    TextQualityMetrics,
)

logger = logging.getLogger(__name__)


class PDFTypeDetector:
    """逐页判断 PDF 类型：scanned / native / mixed"""

    def __init__(self, config: PDFDetectionConfig | None = None):
        self.config = config or PDFDetectionConfig()

    # ----------------------------------------------------------
    # 公开接口
    # ----------------------------------------------------------

    def classify(self, doc: fitz.Document) -> list[PageClassification]:
        """对每一页进行类型分类"""
        results: list[PageClassification] = []
        for page_num in range(len(doc)):
            cls = self._classify_page(doc, page_num)
            results.append(cls)
            logger.debug(
                "Page %d → %s (quality=%.2f, reason=%s)",
                page_num + 1, cls.page_type.value,
                cls.text_layer_quality, cls.quality_reason,
            )
        return results

    # ----------------------------------------------------------
    # 单页分类
    # ----------------------------------------------------------

    def _classify_page(self, doc: fitz.Document, page_idx: int) -> PageClassification:
        page = doc[page_idx]
        page_number = page_idx + 1

        # 强制模式
        if self.config.force_mode:
            return PageClassification(
                page_number=page_number,
                page_type=PageType(self.config.force_mode),
                quality_reason=f"forced mode: {self.config.force_mode}",
            )

        # 1. 提取文本层
        text = page.get_text("text")
        char_count = len(text.strip())

        if char_count < self.config.min_text_chars:
            return PageClassification(
                page_number=page_number,
                page_type=PageType.SCANNED,
                text_coverage=0.0,
                text_layer_quality=0.0,
                quality_reason=f"too few chars ({char_count} < {self.config.min_text_chars})",
            )

        # 2. 质量评估
        metrics = self._evaluate_text_quality(page, text)
        quality_score = self._compute_quality_score(metrics)

        # 3. 低质量文本 → SCANNED
        if metrics.invalid_char_ratio > 0.05:
            return PageClassification(
                page_number=page_number,
                page_type=PageType.SCANNED,
                text_layer_quality=quality_score,
                quality_metrics=metrics,
                quality_reason=f"high invalid char ratio ({metrics.invalid_char_ratio:.2%})",
            )

        if quality_score < self.config.text_quality_threshold:
            return PageClassification(
                page_number=page_number,
                page_type=PageType.SCANNED,
                text_layer_quality=quality_score,
                quality_metrics=metrics,
                quality_reason=f"low quality score ({quality_score:.2f})",
            )

        # 4. 检查嵌入图片面积占比
        has_images, image_area_ratio = self._check_embedded_images(page)

        # 5. 检测公式字体
        has_formula = self._detect_formula_fonts(page)

        # 计算文本覆盖率
        page_rect = page.rect
        page_area = page_rect.width * page_rect.height
        text_dict = page.get_text("dict")
        text_area = 0.0
        for block in text_dict.get("blocks", []):
            if block.get("type") == 0:  # text block
                bbox = block["bbox"]
                text_area += (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
        text_coverage = text_area / page_area if page_area > 0 else 0.0

        # 6. 判断 MIXED
        if image_area_ratio > 0.3 or has_formula:
            reason_parts = []
            if image_area_ratio > 0.3:
                reason_parts.append(f"image area {image_area_ratio:.0%}")
            if has_formula:
                reason_parts.append("formula fonts detected")
            return PageClassification(
                page_number=page_number,
                page_type=PageType.MIXED,
                text_coverage=text_coverage,
                text_layer_quality=quality_score,
                quality_metrics=metrics,
                quality_reason="; ".join(reason_parts),
                has_embedded_images=has_images,
                has_formula_fonts=has_formula,
            )

        # 7. NATIVE
        return PageClassification(
            page_number=page_number,
            page_type=PageType.NATIVE,
            text_coverage=text_coverage,
            text_layer_quality=quality_score,
            quality_metrics=metrics,
            quality_reason="good text layer",
            has_embedded_images=has_images,
            has_formula_fonts=False,
        )

    # ----------------------------------------------------------
    # 文本质量评估
    # ----------------------------------------------------------

    def _evaluate_text_quality(self, page: fitz.Page, text: str) -> TextQualityMetrics:
        char_count = len(text)
        if char_count == 0:
            return TextQualityMetrics()

        # 无效字符率
        invalid_count = sum(
            1 for c in text
            if unicodedata.category(c) in ("Cc", "Cf", "Co", "Cn")
            and c not in ("\n", "\r", "\t", " ")
        )
        invalid_ratio = invalid_count / char_count

        # CJK 字符占比
        cjk_count = sum(1 for c in text if self._is_cjk(c))
        cjk_ratio = cjk_count / char_count

        # 字体数量
        text_dict = page.get_text("dict")
        fonts: set[str] = set()
        for block in text_dict.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    fonts.add(span.get("font", ""))

        # 字符位置分散度（简化计算）
        char_widths: list[float] = []
        for block in text_dict.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    bbox = span.get("bbox", (0, 0, 0, 0))
                    span_text = span.get("text", "")
                    if len(span_text) > 0:
                        char_widths.append((bbox[2] - bbox[0]) / len(span_text))

        variance = 0.0
        if len(char_widths) > 1:
            mean_w = sum(char_widths) / len(char_widths)
            variance = sum((w - mean_w) ** 2 for w in char_widths) / len(char_widths)

        # 语言连贯性 — 简化: 使用常规词比例
        word_like = len(re.findall(r"[\w\u4e00-\u9fff]+", text))
        total_tokens = max(len(text.split()), 1)
        coherence = min(word_like / total_tokens, 1.0)

        return TextQualityMetrics(
            char_count=char_count,
            invalid_char_ratio=invalid_ratio,
            cjk_char_ratio=cjk_ratio,
            font_count=len(fonts),
            avg_char_width_variance=variance,
            language_coherence=coherence,
        )

    def _compute_quality_score(self, m: TextQualityMetrics) -> float:
        """将各指标加权为 0-1 的综合分"""
        score = 1.0
        score -= m.invalid_char_ratio * 5.0  # 无效字符惩罚
        if m.font_count > 20:
            score -= 0.2
        if m.avg_char_width_variance > 50:
            score -= 0.2
        score *= m.language_coherence
        return max(0.0, min(1.0, score))

    # ----------------------------------------------------------
    # 嵌入图片检测
    # ----------------------------------------------------------

    def _check_embedded_images(self, page: fitz.Page) -> tuple[bool, float]:
        page_rect = page.rect
        page_area = page_rect.width * page_rect.height
        if page_area == 0:
            return False, 0.0

        image_list = page.get_images(full=True)
        if not image_list:
            return False, 0.0

        total_image_area = 0.0
        for img in image_list:
            xref = img[0]
            try:
                img_rects = page.get_image_rects(xref)
                for r in img_rects:
                    total_image_area += r.width * r.height
            except Exception:
                pass

        ratio = total_image_area / page_area
        return True, ratio

    # ----------------------------------------------------------
    # 公式字体检测
    # ----------------------------------------------------------

    def _detect_formula_fonts(self, page: fitz.Page) -> bool:
        text_dict = page.get_text("dict")
        for block in text_dict.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    font = span.get("font", "")
                    for pattern in self.config.formula_font_patterns:
                        if pattern.lower() in font.lower():
                            return True
        return False

    # ----------------------------------------------------------
    # 工具
    # ----------------------------------------------------------

    @staticmethod
    def _is_cjk(char: str) -> bool:
        cp = ord(char)
        return (
            (0x4E00 <= cp <= 0x9FFF)
            or (0x3400 <= cp <= 0x4DBF)
            or (0x20000 <= cp <= 0x2A6DF)
            or (0xF900 <= cp <= 0xFAFF)
            or (0x2F800 <= cp <= 0x2FA1F)
        )
