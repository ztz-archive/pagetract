"""模块A：PDF 页面渲染器 — 将 PDF 页面渲染为高分辨率位图"""

from __future__ import annotations

import logging

import fitz  # PyMuPDF
from PIL import Image

from pagetract.config import RenderConfig
from pagetract.models import PageImage

logger = logging.getLogger(__name__)


class PDFRenderer:
    """将 PDF 页面渲染为高分辨率 PNG 图片"""

    def __init__(self, config: RenderConfig | None = None):
        self.config = config or RenderConfig()

    def render_page(self, doc: fitz.Document, page_idx: int) -> list[PageImage]:
        """渲染单页，超长页面自动分割"""
        page = doc[page_idx]
        dpi = self.config.render_dpi
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)

        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

        page_number = page_idx + 1

        # 检查超长页面
        if img.height > self.config.max_page_height_px:
            return self._split_page(img, page_number)

        return [PageImage(
            page_number=page_number,
            image=img,
            width=img.width,
            height=img.height,
        )]

    def render_all(
        self,
        doc: fitz.Document,
        page_indices: list[int] | None = None,
    ) -> list[PageImage]:
        """渲染多页"""
        if page_indices is None:
            page_indices = list(range(len(doc)))

        results: list[PageImage] = []
        for idx in page_indices:
            results.extend(self.render_page(doc, idx))
        return results

    # ----------------------------------------------------------
    # 超长页面分割
    # ----------------------------------------------------------

    def _split_page(self, img: Image.Image, page_number: int) -> list[PageImage]:
        """垂直分割超长页面，带重叠区域"""
        split_h = self.config.split_height
        overlap = self.config.split_overlap
        results: list[PageImage] = []
        y = 0
        idx = 0
        while y < img.height:
            y2 = min(y + split_h, img.height)
            crop = img.crop((0, y, img.width, y2))
            results.append(PageImage(
                page_number=page_number,
                image=crop,
                width=crop.width,
                height=crop.height,
                is_split=True,
                split_index=idx,
            ))
            idx += 1
            y += split_h - overlap
            if y2 == img.height:
                break

        logger.info("Page %d split into %d sub-images", page_number, len(results))
        return results
