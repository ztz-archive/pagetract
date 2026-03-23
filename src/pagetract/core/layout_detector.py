"""模块B：布局检测引擎 — 可插拔架构的区域检测与分类"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from PIL import Image

from pagetract.config import LayoutConfig
from pagetract.models import BlockType, LayoutBlock

logger = logging.getLogger(__name__)


# ============================================================
# 抽象接口
# ============================================================

@runtime_checkable
class LayoutDetectorBackend(Protocol):
    """布局检测后端协议"""
    def detect(self, image: Image.Image) -> list[LayoutBlock]: ...


# ============================================================
# DocLayout-YOLO 后端
# ============================================================

class DocLayoutYOLOBackend:
    """使用 DocLayout-YOLO 进行布局检测"""

    # YOLO 类别 ID → BlockType 映射 (基于 DocLayout-YOLO 标准类别)
    CLASS_MAP: dict[int, BlockType] = {
        0: BlockType.TITLE,
        1: BlockType.TEXT,
        2: BlockType.IMAGE,
        3: BlockType.TABLE,
        4: BlockType.FORMULA,
        5: BlockType.HEADER,
        6: BlockType.FOOTER,
        7: BlockType.PAGE_NUMBER,
        8: BlockType.CAPTION,
        9: BlockType.LIST,
        10: BlockType.CODE,
        11: BlockType.REFERENCE,
    }

    def __init__(self, model_path: str | None = None, confidence: float = 0.5):
        self.confidence = confidence
        self._model = None
        self._model_path = model_path

    def _load_model(self):
        if self._model is not None:
            return
        try:
            from doclayout_yolo import YOLOv10
            if self._model_path:
                self._model = YOLOv10(self._model_path)
            else:
                # 尝试使用 huggingface 上的预训练模型
                from huggingface_hub import hf_hub_download
                model_path = hf_hub_download(
                    repo_id="juliozhao/DocLayout-YOLO-DocStructBench",
                    filename="doclayout_yolo_docstructbench_imgsz1024.pt",
                )
                self._model = YOLOv10(model_path)
        except ImportError:
            logger.warning(
                "doclayout-yolo not installed. Install with: pip install doclayout-yolo"
            )
            raise

    def detect(self, image: Image.Image) -> list[LayoutBlock]:
        self._load_model()
        assert self._model is not None

        results = self._model.predict(image, imgsz=1024, conf=self.confidence)
        blocks: list[LayoutBlock] = []

        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for i in range(len(boxes)):
                cls_id = int(boxes.cls[i].item())
                conf = float(boxes.conf[i].item())
                xyxy = boxes.xyxy[i].cpu().numpy()
                bbox = (int(xyxy[0]), int(xyxy[1]), int(xyxy[2]), int(xyxy[3]))

                block_type = self.CLASS_MAP.get(cls_id, BlockType.TEXT)
                blocks.append(LayoutBlock(
                    block_type=block_type,
                    bbox=bbox,
                    confidence=conf,
                ))

        return blocks


# ============================================================
# 布局检测引擎 (含多栏检测与阅读顺序)
# ============================================================

class LayoutDetector:
    """布局检测引擎 — 包含多栏检测和阅读顺序校正"""

    def __init__(self, config: LayoutConfig | None = None, backend: LayoutDetectorBackend | None = None):
        self.config = config or LayoutConfig()
        if backend is not None:
            self._backend = backend
        elif self.config.engine == "doclayout-yolo":
            self._backend = DocLayoutYOLOBackend(
                confidence=self.config.confidence_threshold
            )
        else:
            raise ValueError(f"Unknown layout engine: {self.config.engine}")

    def detect(self, image: Image.Image, page_number: int = 0) -> list[LayoutBlock]:
        """检测 + 过滤 + 多栏 + 排序"""
        blocks = self._backend.detect(image)

        # 设置页码
        for b in blocks:
            b.page_number = page_number

        # 过滤低置信度
        blocks = [b for b in blocks if b.confidence >= self.config.confidence_threshold]

        # 过滤丢弃类型
        discard_set = set(self.config.discard_types)
        if self.config.discard_types:
            blocks = [b for b in blocks if b.block_type.value not in discard_set]

        # NMS 去重 (移除严重重叠的区域)
        blocks = self._nms(blocks, iou_threshold=0.5)

        # 多栏检测
        if self.config.detect_columns and len(blocks) > 1:
            columns = self._detect_columns(image, blocks)
            if len(columns) > 1:
                for block in blocks:
                    block.column_id = self._assign_column(block.bbox, columns)

        # 合并相邻 text
        if self.config.merge_adjacent_text:
            blocks = self._merge_adjacent_text(blocks)

        # 阅读顺序排序
        if self.config.detect_reading_order:
            blocks = self._sort_reading_order(blocks)

        return blocks

    # ----------------------------------------------------------
    # 多栏检测
    # ----------------------------------------------------------

    def _detect_columns(
        self, image: Image.Image, blocks: list[LayoutBlock]
    ) -> list[tuple[int, int]]:
        """检测页面栏数，返回各栏的 (x_start, x_end)"""
        if not blocks:
            return [(0, image.width)]

        # 用直方图方法检测垂直空白带
        page_width = image.width
        histogram = [0] * page_width

        for b in blocks:
            x1, _, x2, _ = b.bbox
            for x in range(max(0, x1), min(page_width, x2)):
                histogram[x] += 1

        # 找空白区域
        min_gap_width = page_width // 20  # 至少 5% 宽度的空白
        center_region = (page_width * 3 // 10, page_width * 7 // 10)

        gaps: list[tuple[int, int]] = []
        in_gap = False
        gap_start = 0
        for x in range(center_region[0], center_region[1]):
            if histogram[x] == 0:
                if not in_gap:
                    gap_start = x
                    in_gap = True
            else:
                if in_gap and (x - gap_start) >= min_gap_width:
                    gaps.append((gap_start, x))
                in_gap = False

        if not gaps:
            return [(0, page_width)]

        # 按最宽的 gap 分成两栏
        best_gap = max(gaps, key=lambda g: g[1] - g[0])
        return [
            (0, best_gap[0]),
            (best_gap[1], page_width),
        ]

    def _assign_column(
        self, bbox: tuple[int, int, int, int], columns: list[tuple[int, int]]
    ) -> int:
        """将区域分配到最匹配的栏"""
        center_x = (bbox[0] + bbox[2]) / 2
        for i, (x_start, x_end) in enumerate(columns):
            if x_start <= center_x <= x_end:
                return i
        return 0

    # ----------------------------------------------------------
    # 阅读顺序排序
    # ----------------------------------------------------------

    def _sort_reading_order(self, blocks: list[LayoutBlock]) -> list[LayoutBlock]:
        """按 (column_id, y_center) 排序"""
        def sort_key(b: LayoutBlock) -> tuple[int, float]:
            col = b.column_id if b.column_id is not None else 0
            y_center = (b.bbox[1] + b.bbox[3]) / 2
            return (col, y_center)

        blocks.sort(key=sort_key)
        for i, b in enumerate(blocks):
            b.reading_order = i
        return blocks

    # ----------------------------------------------------------
    # 合并相邻 text
    # ----------------------------------------------------------

    def _merge_adjacent_text(
        self, blocks: list[LayoutBlock], gap_threshold: int = 20
    ) -> list[LayoutBlock]:
        """合并垂直方向相邻的 text 块"""
        text_blocks = [b for b in blocks if b.block_type == BlockType.TEXT]
        other_blocks = [b for b in blocks if b.block_type != BlockType.TEXT]

        if len(text_blocks) <= 1:
            return blocks

        text_blocks.sort(key=lambda b: (b.column_id or 0, b.bbox[1]))
        merged: list[LayoutBlock] = []
        current = text_blocks[0]

        for next_block in text_blocks[1:]:
            same_col = (current.column_id or 0) == (next_block.column_id or 0)
            vertical_gap = next_block.bbox[1] - current.bbox[3]
            horizontal_overlap = (
                min(current.bbox[2], next_block.bbox[2])
                - max(current.bbox[0], next_block.bbox[0])
            )
            block_width = min(
                current.bbox[2] - current.bbox[0],
                next_block.bbox[2] - next_block.bbox[0],
            )

            if (same_col and 0 <= vertical_gap <= gap_threshold
                    and horizontal_overlap > block_width * 0.5):
                # 合并
                current = LayoutBlock(
                    block_type=BlockType.TEXT,
                    bbox=(
                        min(current.bbox[0], next_block.bbox[0]),
                        current.bbox[1],
                        max(current.bbox[2], next_block.bbox[2]),
                        next_block.bbox[3],
                    ),
                    confidence=min(current.confidence, next_block.confidence),
                    page_number=current.page_number,
                    column_id=current.column_id,
                )
            else:
                merged.append(current)
                current = next_block

        merged.append(current)
        return other_blocks + merged

    # ----------------------------------------------------------
    # NMS 去重
    # ----------------------------------------------------------

    @staticmethod
    def _nms(
        blocks: list[LayoutBlock],
        iou_threshold: float = 0.5,
        containment_threshold: float = 0.7,
    ) -> list[LayoutBlock]:
        if len(blocks) <= 1:
            return blocks

        blocks.sort(key=lambda b: b.confidence, reverse=True)
        keep: list[LayoutBlock] = []

        for block in blocks:
            should_keep = True
            for kept in keep:
                iou = LayoutDetector._compute_iou(block.bbox, kept.bbox)
                if iou > iou_threshold:
                    should_keep = False
                    break
                # 包含关系检查：一个框大部分在另一个框内，压制低置信度的
                containment = LayoutDetector._compute_containment(block.bbox, kept.bbox)
                if containment > containment_threshold:
                    should_keep = False
                    break
            if should_keep:
                keep.append(block)

        return keep

    @staticmethod
    def _compute_iou(
        a: tuple[int, int, int, int], b: tuple[int, int, int, int]
    ) -> float:
        x1 = max(a[0], b[0])
        y1 = max(a[1], b[1])
        x2 = min(a[2], b[2])
        y2 = min(a[3], b[3])

        if x2 <= x1 or y2 <= y1:
            return 0.0

        intersection = (x2 - x1) * (y2 - y1)
        area_a = (a[2] - a[0]) * (a[3] - a[1])
        area_b = (b[2] - b[0]) * (b[3] - b[1])
        union = area_a + area_b - intersection

        return intersection / union if union > 0 else 0.0

    @staticmethod
    def _compute_containment(
        a: tuple[int, int, int, int], b: tuple[int, int, int, int]
    ) -> float:
        """计算包含率：intersection / min(area_a, area_b)，检测一个框被另一个框包含的情况"""
        x1 = max(a[0], b[0])
        y1 = max(a[1], b[1])
        x2 = min(a[2], b[2])
        y2 = min(a[3], b[3])

        if x2 <= x1 or y2 <= y1:
            return 0.0

        intersection = (x2 - x1) * (y2 - y1)
        area_a = (a[2] - a[0]) * (a[3] - a[1])
        area_b = (b[2] - b[0]) * (b[3] - b[1])
        min_area = min(area_a, area_b)

        return intersection / min_area if min_area > 0 else 0.0
