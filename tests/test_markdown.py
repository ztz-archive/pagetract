"""测试 Markdown 组装器"""

from pagetract.config import MarkdownConfig
from pagetract.core.markdown_assembler import MarkdownAssembler
from pagetract.models import BlockType, ProcessedBlock


def test_basic_assembly():
    blocks = [
        ProcessedBlock(
            block_type=BlockType.TITLE,
            bbox=(10, 10, 500, 50),
            page_number=1,
            reading_order=0,
            content="Test Title",
        ),
        ProcessedBlock(
            block_type=BlockType.TEXT,
            bbox=(10, 60, 500, 200),
            page_number=1,
            reading_order=1,
            content="This is a paragraph.",
        ),
    ]
    config = MarkdownConfig(include_source_markers=False, include_page_markers=False)
    assembler = MarkdownAssembler(config)
    md = assembler.assemble(blocks)

    assert "# Test Title" in md
    assert "This is a paragraph." in md


def test_table_output():
    blocks = [
        ProcessedBlock(
            block_type=BlockType.TABLE,
            bbox=(10, 10, 500, 200),
            page_number=1,
            reading_order=0,
            content="| A | B |\n| --- | --- |\n| 1 | 2 |",
            content_type="markdown_table",
        ),
    ]
    config = MarkdownConfig(include_source_markers=False, include_page_markers=False)
    assembler = MarkdownAssembler(config)
    md = assembler.assemble(blocks)
    assert "| A | B |" in md


def test_formula_output():
    blocks = [
        ProcessedBlock(
            block_type=BlockType.FORMULA,
            bbox=(10, 10, 500, 100),
            page_number=1,
            reading_order=0,
            content="E = mc^2",
        ),
    ]
    config = MarkdownConfig(include_source_markers=False, include_page_markers=False)
    assembler = MarkdownAssembler(config)
    md = assembler.assemble(blocks)
    assert "$$" in md
    assert "E = mc^2" in md


def test_page_markers():
    blocks = [
        ProcessedBlock(
            block_type=BlockType.TEXT,
            bbox=(10, 10, 500, 100),
            page_number=1,
            content="Page 1 content",
        ),
        ProcessedBlock(
            block_type=BlockType.TEXT,
            bbox=(10, 10, 500, 100),
            page_number=2,
            content="Page 2 content",
        ),
    ]
    config = MarkdownConfig(include_page_markers=True, include_source_markers=False)
    assembler = MarkdownAssembler(config)
    md = assembler.assemble(blocks)
    assert "<!-- Page 1 -->" in md
    assert "<!-- Page 2 -->" in md


def test_reference_at_end():
    blocks = [
        ProcessedBlock(
            block_type=BlockType.TEXT,
            bbox=(10, 10, 500, 100),
            page_number=1,
            reading_order=0,
            content="Main text",
        ),
        ProcessedBlock(
            block_type=BlockType.REFERENCE,
            bbox=(10, 10, 500, 100),
            page_number=5,
            reading_order=0,
            content="[1] Smith et al. 2024",
        ),
    ]
    config = MarkdownConfig(include_source_markers=False, include_page_markers=False)
    assembler = MarkdownAssembler(config)
    md = assembler.assemble(blocks)

    # Reference should be at end
    text_pos = md.find("Main text")
    ref_pos = md.find("References")
    assert ref_pos > text_pos
