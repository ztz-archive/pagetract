"""模块E：图片保存器 — 裁剪并保存图片区域"""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

from pagetract.config import ImageExtractionConfig
from pagetract.core.region_dispatcher import ImageCropRequest, crop_with_padding
from pagetract.models import BlockType, LayoutBlock

logger = logging.getLogger(__name__)


class ImageSaver:
    """将 IMAGE 区域裁剪保存为独立文件"""

    def __init__(self, config: ImageExtractionConfig | None = None):
        self.config = config or ImageExtractionConfig()

    def save_image(
        self,
        crop_request: ImageCropRequest,
        output_dir: str | Path,
        fig_index: int = 1,
    ) -> str | None:
        """裁剪并保存单张图片，返回相对路径"""
        output_dir = Path(output_dir)
        images_dir = output_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        image = crop_request.page_image
        bbox = crop_request.bbox

        # 检查尺寸
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        if w < self.config.min_size or h < self.config.min_size:
            logger.debug("Image too small (%dx%d), skipping", w, h)
            return None

        cropped = crop_with_padding(image, bbox, padding=self.config.padding)

        fmt = self.config.format.lower()
        filename = f"page{crop_request.page_number}_fig{fig_index}.{fmt}"
        filepath = images_dir / filename

        save_args = {}
        if fmt == "jpeg" or fmt == "jpg":
            save_args["quality"] = self.config.quality
            if cropped.mode == "RGBA":
                cropped = cropped.convert("RGB")

        cropped.save(filepath, **save_args)
        logger.debug("Saved image: %s", filepath)

        return f"images/{filename}"

    def save_table_backup(
        self,
        crop_request: ImageCropRequest,
        output_dir: str | Path,
        table_index: int = 1,
    ) -> str | None:
        """保存表格区域的图片备份"""
        output_dir = Path(output_dir)
        images_dir = output_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        cropped = crop_with_padding(
            crop_request.page_image,
            crop_request.bbox,
            padding=self.config.padding,
        )

        fmt = self.config.format.lower()
        filename = f"page{crop_request.page_number}_table{table_index}.{fmt}"
        filepath = images_dir / filename
        cropped.save(filepath)

        return f"images/{filename}"

    def save_embedded_image(
        self,
        image: Image.Image,
        page_number: int,
        fig_index: int,
        output_dir: str | Path,
    ) -> str | None:
        """保存从原生 PDF 直接提取的嵌入图片"""
        output_dir = Path(output_dir)
        images_dir = output_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        if image.width < self.config.min_size or image.height < self.config.min_size:
            return None

        fmt = self.config.format.lower()
        filename = f"page{page_number}_fig{fig_index}.{fmt}"
        filepath = images_dir / filename

        save_args = {}
        if fmt in ("jpeg", "jpg"):
            save_args["quality"] = self.config.quality
            if image.mode == "RGBA":
                image = image.convert("RGB")

        image.save(filepath, **save_args)
        return f"images/{filename}"


def get_alt_text(
    block: LayoutBlock,
    all_blocks: list[LayoutBlock],
    page_area: float,
) -> tuple[str, bool]:
    """获取图片的 alt text。返回 (alt_text, need_vlm)."""
    # 1. 找相邻 caption
    for other in all_blocks:
        if other.block_type != BlockType.CAPTION:
            continue
        if other.page_number != block.page_number:
            continue
        # 检查是否相邻（垂直距离 < 50px）
        vertical_dist = min(
            abs(other.bbox[1] - block.bbox[3]),
            abs(block.bbox[1] - other.bbox[3]),
        )
        if vertical_dist < 50:
            return other.block_type.value, False  # 使用 caption 文本（后续 VLM 识别）

    # 2. 大图片 → 需要 VLM 生成描述
    image_area = (block.bbox[2] - block.bbox[0]) * (block.bbox[3] - block.bbox[1])
    if page_area > 0 and image_area / page_area > 0.1:
        return "", True  # 需要 VLM

    # 3. 默认
    return f"Page {block.page_number}, Figure", False
