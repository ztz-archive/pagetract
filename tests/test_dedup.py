"""测试同页块去重逻辑"""

from pagetract.core.pipeline import Pipeline
from pagetract.models import BlockType, ProcessedBlock


def _block(page: int, bbox: tuple, content: str = "", btype: BlockType = BlockType.TEXT):
    return ProcessedBlock(
        block_type=btype, bbox=bbox, page_number=page, content=content, source="vlm",
    )


def test_dedup_contained_blocks():
    """完全包含的块应被去重，保留内容更长的"""
    blocks = [
        _block(1, (0, 0, 1000, 500), "short"),
        _block(1, (100, 50, 900, 450), "this is the longer and more complete content"),
    ]
    result = Pipeline._deduplicate_same_page_blocks(blocks, containment_threshold=0.6)
    assert len(result) == 1
    assert "longer" in result[0].content


def test_dedup_no_overlap():
    """不重叠的块不应被去重"""
    blocks = [
        _block(1, (0, 0, 100, 100), "block A"),
        _block(1, (200, 200, 400, 400), "block B"),
    ]
    result = Pipeline._deduplicate_same_page_blocks(blocks, containment_threshold=0.6)
    assert len(result) == 2


def test_dedup_different_pages():
    """不同页的重叠块不应被去重"""
    blocks = [
        _block(1, (0, 0, 500, 500), "page 1"),
        _block(2, (0, 0, 500, 500), "page 2"),
    ]
    result = Pipeline._deduplicate_same_page_blocks(blocks, containment_threshold=0.6)
    assert len(result) == 2


def test_dedup_multiple_overlaps():
    """多个重叠块只保留内容最完整的"""
    blocks = [
        _block(1, (10, 10, 500, 300), "a"),
        _block(1, (20, 20, 490, 290), "bb"),
        _block(1, (30, 30, 480, 280), "the longest content here is retained"),
        _block(1, (700, 0, 1000, 200), "separate block"),
    ]
    result = Pipeline._deduplicate_same_page_blocks(blocks, containment_threshold=0.6)
    # 前三个互相包含，保留最长的；第四个独立
    assert len(result) == 2
    contents = {b.content for b in result}
    assert "the longest content here is retained" in contents
    assert "separate block" in contents


def test_bbox_containment():
    # 完全包含
    assert Pipeline._bbox_containment((0, 0, 1000, 500), (200, 100, 800, 400)) > 0.99
    # 不重叠
    assert Pipeline._bbox_containment((0, 0, 100, 100), (200, 200, 300, 300)) == 0.0
    # 部分重叠
    c = Pipeline._bbox_containment((0, 0, 200, 200), (100, 100, 300, 300))
    assert 0 < c < 1
