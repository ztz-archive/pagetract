"""PageTract SDK 主入口"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from pagetract.config import PagetractConfig, load_config
from pagetract.core.pipeline import Pipeline
from pagetract.models import ConversionResult, CostEstimate, VideoConversionResult


class PageTract:
    """pagetract SDK 主入口类

    用法:
        converter = PageTract(config_path="config.yaml")
        result = converter.convert("input.pdf", output_dir="./output")
        print(result.markdown)
    """

    def __init__(
        self,
        config_path: str | Path | None = None,
        config: PagetractConfig | None = None,
        **overrides: Any,
    ):
        if config is not None:
            self._config = config
        else:
            self._config = load_config(
                config_path=config_path,
                overrides=overrides if overrides else None,
            )
        self._pipeline = Pipeline(self._config)

    @property
    def config(self) -> PagetractConfig:
        return self._config

    # ----------------------------------------------------------
    # 同步接口
    # ----------------------------------------------------------

    def convert(
        self,
        pdf_path: str | Path,
        output_dir: str | Path | None = None,
    ) -> ConversionResult:
        """同步转换 PDF → Markdown"""
        pdf_path = str(pdf_path)
        output_dir = str(output_dir or self._config.general.output_dir)
        return self._pipeline.convert(pdf_path, output_dir)

    def estimate(self, pdf_path: str | Path) -> CostEstimate:
        """成本预估（dry-run, 不调用 VLM）"""
        return self._pipeline.estimate(str(pdf_path))

    # ----------------------------------------------------------
    # 异步接口
    # ----------------------------------------------------------

    async def aconvert(
        self,
        pdf_path: str | Path,
        output_dir: str | Path | None = None,
    ) -> ConversionResult:
        """异步转换 PDF → Markdown"""
        pdf_path = str(pdf_path)
        output_dir = str(output_dir or self._config.general.output_dir)
        return await self._pipeline.aconvert(pdf_path, output_dir)

    # ----------------------------------------------------------
    # 进度回调
    # ----------------------------------------------------------

    def set_progress_callback(self, callback):
        """设置进度回调函数"""
        self._pipeline.set_progress_callback(callback)

    # ----------------------------------------------------------
    # 视频转换
    # ----------------------------------------------------------

    def convert_video(
        self,
        url: str,
        output_dir: str | Path | None = None,
        audio_only: bool = False,
        video_only: bool = False,
    ) -> VideoConversionResult:
        """同步转换视频 → 两份 Markdown（音频转录 + 视频理解）"""
        output_dir = str(output_dir or self._config.general.output_dir)
        return asyncio.get_event_loop().run_until_complete(
            self.aconvert_video(url, output_dir, audio_only, video_only)
        )

    async def aconvert_video(
        self,
        url: str,
        output_dir: str | Path | None = None,
        audio_only: bool = False,
        video_only: bool = False,
    ) -> VideoConversionResult:
        """异步转换视频 → 两份 Markdown（音频转录 + 视频理解）"""
        from pagetract.core.video_processor import VideoProcessor

        output_dir = str(output_dir or self._config.general.output_dir)
        processor = VideoProcessor(self._config.video, self._config.vlm)
        return await processor.process(
            url, output_dir,
            audio_only=audio_only,
            video_only=video_only,
        )
