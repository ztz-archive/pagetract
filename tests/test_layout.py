"""测试布局检测引擎（不含 YOLO 模型）"""

from PIL import Image

from pagetract.config import LayoutConfig
from pagetract.core.layout_detector import LayoutDetector
from pagetract.models import BlockType, LayoutBlock


class MockBackend:
    """Mock 布局检测后端"""
    def __init__(self, blocks: list[LayoutBlock]):
        self._blocks = blocks

    def detect(self, image: Image.Image) -> list[LayoutBlock]:
        return self._blocks


def test_nms():
    blocks = [
        LayoutBlock(BlockType.TEXT, (10, 10, 200, 100), confidence=0.9),
        LayoutBlock(BlockType.TEXT, (15, 12, 198, 98), confidence=0.8),  # 高度重叠
        LayoutBlock(BlockType.IMAGE, (300, 10, 500, 200), confidence=0.95),
    ]
    result = LayoutDetector._nms(blocks, iou_threshold=0.5)
    assert len(result) == 2  # 重叠的应该被去掉


def test_iou():
    a = (0, 0, 100, 100)
    b = (0, 0, 100, 100)
    assert LayoutDetector._compute_iou(a, b) == 1.0

    a = (0, 0, 100, 100)
    b = (200, 200, 300, 300)
    assert LayoutDetector._compute_iou(a, b) == 0.0


def test_reading_order():
    blocks = [
        LayoutBlock(BlockType.TEXT, (10, 200, 200, 300), confidence=0.9, page_number=1),
        LayoutBlock(BlockType.TITLE, (10, 10, 200, 50), confidence=0.9, page_number=1),
        LayoutBlock(BlockType.IMAGE, (300, 100, 500, 250), confidence=0.9, page_number=1),
    ]
    config = LayoutConfig(detect_columns=False, merge_adjacent_text=False)
    backend = MockBackend(blocks)
    detector = LayoutDetector(config=config, backend=backend)

    img = Image.new("RGB", (500, 500))
    result = detector.detect(img, page_number=1)

    assert len(result) == 3
    # 应该按 y 坐标排序 (TITLE at y=10 first)
    assert result[0].block_type == BlockType.TITLE
    assert result[0].reading_order == 0


def test_discard_types():
    blocks = [
        LayoutBlock(BlockType.TEXT, (10, 10, 200, 100), confidence=0.9, page_number=1),
        LayoutBlock(BlockType.HEADER, (10, 0, 200, 10), confidence=0.9, page_number=1),
        LayoutBlock(BlockType.FOOTER, (10, 900, 200, 950), confidence=0.9, page_number=1),
    ]
    config = LayoutConfig(discard_types=["header", "footer"], detect_columns=False)
    backend = MockBackend(blocks)
    detector = LayoutDetector(config=config, backend=backend)

    img = Image.new("RGB", (500, 1000))
    result = detector.detect(img, page_number=1)

    assert len(result) == 1
    assert result[0].block_type == BlockType.TEXT
