"""测试数据模型"""

from pagetract.models import (
    BlockType,
    ConversionMetadata,
    LayoutBlock,
    PageClassification,
    PageImage,
    PageType,
    ProcessedBlock,
    TextQualityMetrics,
)


def test_page_type_enum():
    assert PageType.SCANNED.value == "scanned"
    assert PageType.NATIVE.value == "native"
    assert PageType.MIXED.value == "mixed"


def test_block_type_enum():
    assert BlockType.TITLE.value == "title"
    assert BlockType.TABLE.value == "table"
    assert BlockType.FORMULA.value == "formula"


def test_text_quality_metrics_defaults():
    m = TextQualityMetrics()
    assert m.char_count == 0
    assert m.invalid_char_ratio == 0.0


def test_page_classification():
    pc = PageClassification(
        page_number=1,
        page_type=PageType.NATIVE,
        text_coverage=0.8,
    )
    assert pc.page_number == 1
    assert pc.page_type == PageType.NATIVE


def test_layout_block():
    block = LayoutBlock(
        block_type=BlockType.TEXT,
        bbox=(10, 20, 300, 100),
        confidence=0.95,
        page_number=1,
    )
    assert block.bbox == (10, 20, 300, 100)
    assert block.confidence == 0.95


def test_processed_block():
    pb = ProcessedBlock(
        block_type=BlockType.TEXT,
        bbox=(0, 0, 100, 50),
        page_number=1,
        content="Hello World",
    )
    assert pb.content == "Hello World"
    assert pb.source == "vlm"


def test_conversion_metadata():
    meta = ConversionMetadata(total_pages=10)
    assert meta.total_pages == 10
    assert meta.api_calls == 0
    assert meta.cache_hits == {"layout": 0, "vlm": 0}
