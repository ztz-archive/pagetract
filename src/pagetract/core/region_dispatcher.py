"""模块C：区域处理分发器 — 整页送 VLM + 坐标提示策略"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from PIL import Image

from pagetract.config import VLMConfig
from pagetract.models import BlockType, LayoutBlock

logger = logging.getLogger(__name__)


@dataclass
class VLMRequest:
    """送给 VLM 的单次请求"""
    page_image: Image.Image
    page_number: int
    regions: list[tuple[tuple[int, int, int, int], BlockType]]
    # 降采样后的坐标（如果有缩放）
    downsample_ratio: float = 1.0


@dataclass
class ImageCropRequest:
    """图片裁剪请求"""
    page_image: Image.Image
    page_number: int
    bbox: tuple[int, int, int, int]
    block_index: int = 0


@dataclass
class DispatchResult:
    """分发结果"""
    vlm_requests: list[VLMRequest] = field(default_factory=list)
    image_crops: list[ImageCropRequest] = field(default_factory=list)
    table_crops: list[ImageCropRequest] = field(default_factory=list)  # 表格备份图片


class RegionDispatcher:
    """根据区域类型分发到不同处理器"""

    # 需要送 VLM 识别的区域类型
    VLM_TYPES = {
        BlockType.TITLE, BlockType.TEXT, BlockType.CAPTION,
        BlockType.LIST, BlockType.REFERENCE, BlockType.CODE,
        BlockType.TABLE, BlockType.FORMULA,
    }

    def __init__(self, config: VLMConfig | None = None):
        self.config = config or VLMConfig()

    def dispatch(
        self,
        page_image: Image.Image,
        page_number: int,
        blocks: list[LayoutBlock],
    ) -> DispatchResult:
        """对一页的所有区域进行分发"""
        result = DispatchResult()

        vlm_blocks: list[LayoutBlock] = []
        image_blocks: list[LayoutBlock] = []

        for block in blocks:
            if block.block_type == BlockType.IMAGE:
                image_blocks.append(block)
            elif block.block_type in self.VLM_TYPES:
                vlm_blocks.append(block)
                # 表格同时保存备份图片
                if block.block_type == BlockType.TABLE:
                    result.table_crops.append(ImageCropRequest(
                        page_image=page_image,
                        page_number=page_number,
                        bbox=block.bbox,
                    ))

        # 图片区域 → 裁剪
        for i, block in enumerate(image_blocks):
            result.image_crops.append(ImageCropRequest(
                page_image=page_image,
                page_number=page_number,
                bbox=block.bbox,
                block_index=i,
            ))

        # VLM 区域 → 智能批量合并
        if vlm_blocks:
            # 准备 VLM 图片（降采样）
            vlm_image, ratio = self._prepare_image_for_vlm(page_image)

            if self.config.batch_regions:
                vlm_requests = self._smart_batch_regions(
                    vlm_image, page_number, vlm_blocks, ratio
                )
            else:
                vlm_requests = self._single_region_requests(
                    vlm_image, page_number, vlm_blocks, ratio
                )
            result.vlm_requests = vlm_requests

        return result

    # ----------------------------------------------------------
    # VLM 图片预处理（降采样）
    # ----------------------------------------------------------

    def _prepare_image_for_vlm(self, page_image: Image.Image) -> tuple[Image.Image, float]:
        ratio = self.config.vlm_downsample_ratio
        if ratio >= 1.0:
            return page_image, 1.0

        new_w = int(page_image.width * ratio)
        new_h = int(page_image.height * ratio)
        downsampled = page_image.resize((new_w, new_h), Image.Resampling.LANCZOS)
        return downsampled, ratio

    # ----------------------------------------------------------
    # 智能批量合并
    # ----------------------------------------------------------

    def _smart_batch_regions(
        self,
        vlm_image: Image.Image,
        page_number: int,
        blocks: list[LayoutBlock],
        ratio: float,
    ) -> list[VLMRequest]:
        """将同页区域智能分组为批量 VLM 请求"""
        max_per_batch = self.config.max_regions_per_batch
        max_distance = self.config.max_region_distance

        # 复杂页面采用保守策略
        if len(blocks) > self.config.complexity_threshold:
            max_per_batch = min(max_per_batch, 3)
            max_distance = max_distance // 2

        # 极简单页面：只有 1-2 个纯文本区域
        text_only = all(b.block_type in (BlockType.TEXT, BlockType.TITLE) for b in blocks)
        if text_only and len(blocks) <= 2:
            # 不指定坐标，直接让 VLM 识别整页
            return [VLMRequest(
                page_image=vlm_image,
                page_number=page_number,
                regions=[(self._scale_bbox(b.bbox, ratio), b.block_type) for b in blocks],
                downsample_ratio=ratio,
            )]

        # 按类型和距离分组
        blocks_sorted = sorted(blocks, key=lambda b: (b.block_type.value, b.bbox[1]))
        batches: list[list[LayoutBlock]] = []
        current_batch: list[LayoutBlock] = [blocks_sorted[0]]

        for block in blocks_sorted[1:]:
            last = current_batch[-1]
            same_type = block.block_type == last.block_type
            distance = abs(block.bbox[1] - last.bbox[3])

            if (same_type and distance < max_distance
                    and len(current_batch) < max_per_batch):
                current_batch.append(block)
            else:
                batches.append(current_batch)
                current_batch = [block]
        batches.append(current_batch)

        requests: list[VLMRequest] = []
        for batch in batches:
            regions = [
                (self._scale_bbox(b.bbox, ratio), b.block_type)
                for b in batch
            ]
            requests.append(VLMRequest(
                page_image=vlm_image,
                page_number=page_number,
                regions=regions,
                downsample_ratio=ratio,
            ))

        return requests

    # ----------------------------------------------------------
    # 单区域请求
    # ----------------------------------------------------------

    def _single_region_requests(
        self,
        vlm_image: Image.Image,
        page_number: int,
        blocks: list[LayoutBlock],
        ratio: float,
    ) -> list[VLMRequest]:
        return [
            VLMRequest(
                page_image=vlm_image,
                page_number=page_number,
                regions=[(self._scale_bbox(b.bbox, ratio), b.block_type)],
                downsample_ratio=ratio,
            )
            for b in blocks
        ]

    # ----------------------------------------------------------
    # 坐标动态调整
    # ----------------------------------------------------------

    @staticmethod
    def adjust_bbox_for_vlm(
        bbox: tuple[int, int, int, int],
        block_type: BlockType,
        confidence: float,
        page_bounds: tuple[int, int] = (0, 0),
    ) -> tuple[int, int, int, int]:
        """根据置信度和区域类型动态扩展 bbox"""
        expansion = int(10 * (1 - confidence))
        if block_type == BlockType.TABLE:
            expansion = max(expansion, 15)
        elif block_type == BlockType.FORMULA:
            expansion = max(expansion, 8)

        x1, y1, x2, y2 = bbox
        x1 = max(0, x1 - expansion)
        y1 = max(0, y1 - expansion)
        x2 = x2 + expansion
        y2 = y2 + expansion
        if page_bounds[0] > 0:
            x2 = min(x2, page_bounds[0])
        if page_bounds[1] > 0:
            y2 = min(y2, page_bounds[1])
        return (x1, y1, x2, y2)

    @staticmethod
    def _scale_bbox(
        bbox: tuple[int, int, int, int], ratio: float
    ) -> tuple[int, int, int, int]:
        if ratio == 1.0:
            return bbox
        return (
            int(bbox[0] * ratio),
            int(bbox[1] * ratio),
            int(bbox[2] * ratio),
            int(bbox[3] * ratio),
        )


def crop_with_padding(
    image: Image.Image, bbox: tuple[int, int, int, int], padding: int = 8
) -> Image.Image:
    """裁剪图片区域（带边距）"""
    x1, y1, x2, y2 = bbox
    x1 = max(0, x1 - padding)
    y1 = max(0, y1 - padding)
    x2 = min(image.width, x2 + padding)
    y2 = min(image.height, y2 + padding)
    return image.crop((x1, y1, x2, y2))
