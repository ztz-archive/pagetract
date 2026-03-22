"""测试 Prompt 生成"""

from pagetract.core.prompts import get_batch_prompt, get_prompt
from pagetract.models import BlockType


def test_text_prompt():
    prompt = get_prompt(BlockType.TEXT, (10, 20, 300, 100))
    assert "(10, 20)" in prompt
    assert "(300, 100)" in prompt
    assert "OCR" in prompt


def test_formula_prompt():
    prompt = get_prompt(BlockType.FORMULA, (0, 0, 500, 200))
    assert "LaTeX" in prompt
    assert "(0, 0)" in prompt


def test_batch_prompt():
    regions = [
        ((10, 10, 200, 50), BlockType.TITLE),
        ((10, 60, 200, 200), BlockType.TEXT),
    ]
    prompt = get_batch_prompt(regions)
    assert "[REGION_1]" in prompt
    assert "[REGION_2]" in prompt
    assert "title" in prompt


def test_custom_prompt():
    custom = {"text": "Custom OCR: ({x1},{y1}) to ({x2},{y2})"}
    prompt = get_prompt(BlockType.TEXT, (1, 2, 3, 4), custom_prompts=custom)
    assert "Custom OCR" in prompt
    assert "(1,2)" in prompt
