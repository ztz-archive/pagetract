"""模块D：VLM OCR 引擎 — 调用视觉 LLM 进行高精度内容识别"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import re
from typing import Any

import httpx
from PIL import Image

from pagetract.config import VLMConfig
from pagetract.core.prompts import get_batch_prompt, get_prompt, PROMPTS
from pagetract.core.region_dispatcher import VLMRequest
from pagetract.models import BlockType, RecognitionResult

logger = logging.getLogger(__name__)


class VLMEngine:
    """VLM OCR 引擎 — 通过 OpenAI 兼容 API 调用视觉 LLM"""

    def __init__(self, config: VLMConfig | None = None):
        self.config = config or VLMConfig()
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.timeout, connect=10.0),
                limits=httpx.Limits(
                    max_connections=self.config.connection_pool_size,
                    max_keepalive_connections=self.config.connection_pool_size,
                ),
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ----------------------------------------------------------
    # 单区域识别
    # ----------------------------------------------------------

    async def recognize(
        self,
        page_image: Image.Image,
        target_bbox: tuple[int, int, int, int],
        block_type: BlockType,
        context: str | None = None,
    ) -> RecognitionResult:
        """识别单个区域"""
        prompt = get_prompt(
            block_type, target_bbox,
            custom_prompts=self.config.custom_prompts or None,
        )
        if context:
            prompt = f"文档上下文: {context}\n\n{prompt}"

        response = await self._call_vlm(page_image, prompt)

        content_type = self._infer_content_type(block_type)
        return RecognitionResult(
            content=response,
            content_type=content_type,
            target_bbox=target_bbox,
            raw_response=response,
        )

    # ----------------------------------------------------------
    # 批量区域识别
    # ----------------------------------------------------------

    async def recognize_batch(
        self,
        page_image: Image.Image,
        targets: list[tuple[tuple[int, int, int, int], BlockType]],
        context: str | None = None,
    ) -> list[RecognitionResult]:
        """同一页面多区域批量识别"""
        if len(targets) == 1:
            bbox, btype = targets[0]
            result = await self.recognize(page_image, bbox, btype, context)
            return [result]

        prompt = get_batch_prompt(
            targets,
            custom_prompts=self.config.custom_prompts or None,
        )
        if context:
            prompt = f"文档上下文: {context}\n\n{prompt}"

        response = await self._call_vlm(page_image, prompt)

        # 解析批量响应
        return self._parse_batch_response(response, targets)

    # ----------------------------------------------------------
    # 处理 VLM 请求
    # ----------------------------------------------------------

    async def process_request(self, request: VLMRequest) -> list[RecognitionResult]:
        """处理一个 VLMRequest"""
        context = self.config.document_context or None
        return await self.recognize_batch(
            request.page_image,
            request.regions,
            context,
        )

    async def process_requests(self, requests: list[VLMRequest]) -> list[list[RecognitionResult]]:
        """并发处理多个 VLMRequest"""
        tasks = [self.process_request(req) for req in requests]
        return await asyncio.gather(*tasks, return_exceptions=False)

    # ----------------------------------------------------------
    # 图片 alt text 生成
    # ----------------------------------------------------------

    async def generate_image_alt(
        self, page_image: Image.Image, bbox: tuple[int, int, int, int]
    ) -> str:
        """为图片区域生成 alt text 描述"""
        prompt = get_prompt(
            BlockType.IMAGE, bbox,
            custom_prompts=self.config.custom_prompts or None,
        )
        return await self._call_vlm(page_image, prompt)

    # ----------------------------------------------------------
    # VLM API 调用
    # ----------------------------------------------------------

    async def _call_vlm(self, image: Image.Image, prompt: str) -> str:
        """调用 VLM API (带重试和并发控制)"""
        async with self._semaphore:
            last_error: Exception | None = None
            for attempt in range(self.config.max_retries + 1):
                try:
                    return await self._do_call(image, prompt)
                except Exception as e:
                    last_error = e
                    if attempt < self.config.max_retries:
                        wait = 2 ** attempt
                        logger.warning(
                            "VLM call failed (attempt %d/%d): %s, retrying in %ds",
                            attempt + 1, self.config.max_retries + 1, e, wait,
                        )
                        await asyncio.sleep(wait)
            raise RuntimeError(f"VLM call failed after {self.config.max_retries + 1} attempts") from last_error

    async def _do_call(self, image: Image.Image, prompt: str) -> str:
        """实际的 API 调用"""
        client = await self._get_client()
        base64_image = self._image_to_base64(image)

        url = f"{self.config.api_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

        payload: dict[str, Any] = {
            "model": self.config.model,
            "temperature": self.config.temperature,
            "enable_thinking": False,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_image}",
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                }
            ],
            "max_tokens": 4096,
        }

        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("VLM returned empty choices")

        return choices[0]["message"]["content"]

    # ----------------------------------------------------------
    # 响应解析
    # ----------------------------------------------------------

    def _parse_batch_response(
        self,
        response: str,
        targets: list[tuple[tuple[int, int, int, int], BlockType]],
    ) -> list[RecognitionResult]:
        """解析批量响应，按 [REGION_N] 拆分"""
        results: list[RecognitionResult] = []

        # 用正则按 [REGION_N] 分割
        parts = re.split(r"\[REGION_(\d+)\]", response)

        # parts: ['', '1', 'content1', '2', 'content2', ...]
        region_contents: dict[int, str] = {}
        i = 1
        while i < len(parts) - 1:
            region_num = int(parts[i])
            content = parts[i + 1].strip()
            region_contents[region_num] = content
            i += 2

        for idx, (bbox, block_type) in enumerate(targets):
            region_num = idx + 1
            content = region_contents.get(region_num, "")

            if not content and len(targets) == 1:
                # 只有一个区域时, 响应可能没有 [REGION_1] 标记
                content = response.strip()

            results.append(RecognitionResult(
                content=content,
                content_type=self._infer_content_type(block_type),
                target_bbox=bbox,
                raw_response=response,
            ))

        return results

    # ----------------------------------------------------------
    # 工具
    # ----------------------------------------------------------

    @staticmethod
    def _image_to_base64(image: Image.Image) -> str:
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    @staticmethod
    def _infer_content_type(block_type: BlockType) -> str:
        if block_type == BlockType.TABLE:
            return "markdown_table"
        if block_type == BlockType.FORMULA:
            return "latex"
        return "text"


# ============================================================
# VLM 输出校验器
# ============================================================

class VLMResponseValidator:
    """校验 VLM 输出的合理性"""

    def validate(
        self,
        result: RecognitionResult,
        block_type: BlockType,
        bbox: tuple[int, int, int, int],
        page_image: Image.Image | None = None,
    ) -> RecognitionResult:
        """校验并标注结果"""
        warnings: list[str] = []

        # 1. 检查输出是否为空
        if not result.content.strip():
            warnings.append("empty output")
            result.validation_passed = False

        # 2. 检查输出长度与区域面积比例
        area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
        content_len = len(result.content)
        if area > 0:
            density = content_len / (area / 1000)
            if density > 50:
                warnings.append(f"output too long for area (density={density:.1f})")

        # 3. 表格格式检查
        if block_type == BlockType.TABLE:
            if "|" not in result.content and "<table" not in result.content.lower():
                warnings.append("table output missing pipe or table tag")

        # 4. LaTeX 格式检查
        if block_type == BlockType.FORMULA:
            if "$" not in result.content and "\\" not in result.content:
                warnings.append("formula output missing LaTeX syntax")

        if warnings:
            result.validation_warning = "; ".join(warnings)
            if result.validation_passed:
                result.validation_passed = len(warnings) <= 1  # 多个警告才标记失败

        return result
