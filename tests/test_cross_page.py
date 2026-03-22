"""测试跨页合并器"""

from pagetract.core.cross_page_merger import CrossPageAggregator
from pagetract.models import BlockType, ProcessedBlock


def test_merge_tables():
    table1 = "| A | B |\n| --- | --- |\n| 1 | 2 |"
    table2 = "| A | B |\n| --- | --- |\n| 3 | 4 |"
    merged = CrossPageAggregator._merge_tables(table1, table2)
    assert "| 1 | 2 |" in merged
    assert "| 3 | 4 |" in merged
    # 应该只有一个表头
    assert merged.count("| --- | --- |") == 1


def test_table_columns_match():
    t1 = "| A | B | C |\n| --- | --- | --- |"
    t2 = "| A | B | C |\n| --- | --- | --- |"
    assert CrossPageAggregator._table_columns_match(t1, t2) is True

    t3 = "| A | B |\n| --- | --- |"
    assert CrossPageAggregator._table_columns_match(t1, t3) is False


def test_detect_no_cross_page():
    blocks = [
        ProcessedBlock(
            block_type=BlockType.TEXT,
            bbox=(10, 100, 500, 200),
            page_number=1,
            content="Normal text",
        ),
    ]
    aggregator = CrossPageAggregator()
    result = aggregator.detect_and_merge(blocks)
    assert len(result) == 1


def test_detect_cross_page_paragraph():
    blocks = [
        ProcessedBlock(
            block_type=BlockType.TEXT,
            bbox=(10, 2800, 500, 3000),  # 底部
            page_number=1,
            reading_order=0,
            content="This sentence continues on the next",
        ),
        ProcessedBlock(
            block_type=BlockType.TEXT,
            bbox=(10, 10, 500, 100),  # 顶部
            page_number=2,
            reading_order=0,
            content="page without ending.",
        ),
    ]
    aggregator = CrossPageAggregator(page_heights={1: 3000, 2: 3000})
    result = aggregator.detect_and_merge(blocks)

    # 应该合并为一个
    assert len(result) == 1
    assert "continues" in result[0].content
    assert "page without" in result[0].content
