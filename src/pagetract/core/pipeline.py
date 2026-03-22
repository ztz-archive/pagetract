"""流水线并行架构 — 渲染→检测→VLM 三阶段流水线"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

import fitz

from pagetract.config import PagetractConfig
from pagetract.core.cache import CacheManager
from pagetract.core.cross_page_merger import CrossPageAggregator
from pagetract.core.image_saver import ImageSaver, get_alt_text
from pagetract.core.layout_detector import LayoutDetector
from pagetract.core.markdown_assembler import MarkdownAssembler
from pagetract.core.native_extractor import NativeTextExtractor
from pagetract.core.pdf_detector import PDFTypeDetector
from pagetract.core.preprocessor import PagePreprocessor
from pagetract.core.region_dispatcher import RegionDispatcher, crop_with_padding
from pagetract.core.renderer import PDFRenderer
from pagetract.core.vlm_engine import VLMEngine
from pagetract.models import (
    BlockType,
    ConversionMetadata,
    ConversionResult,
    CostEstimate,
    LayoutBlock,
    PageImage,
    PageType,
    ProcessedBlock,
)

logger = logging.getLogger(__name__)


class Pipeline:
    """核心处理流水线"""

    def __init__(self, config: PagetractConfig):
        self.config = config
        self.detector = PDFTypeDetector(config.pdf_detection)
        self.preprocessor = PagePreprocessor(config.preprocessing)
        self.renderer = PDFRenderer(config.render)
        self.native_extractor = NativeTextExtractor(config.native_extract)
        self.layout_detector = LayoutDetector(config.layout)
        self.dispatcher = RegionDispatcher(config.vlm)
        self.vlm_engine = VLMEngine(config.vlm)
        self.image_saver = ImageSaver(config.image_extraction)
        self.assembler = MarkdownAssembler(config.markdown)
        self.cache = CacheManager(config.cache)

        self._progress_callback: Callable[[dict[str, Any]], None] | None = None

    def set_progress_callback(self, callback: Callable[[dict[str, Any]], None]) -> None:
        self._progress_callback = callback

    def _report_progress(self, **kwargs: Any) -> None:
        if self._progress_callback:
            self._progress_callback(kwargs)

    # ----------------------------------------------------------
    # 同步入口
    # ----------------------------------------------------------

    def convert(self, pdf_path: str, output_dir: str) -> ConversionResult:
        """同步转换接口"""
        return asyncio.run(self.aconvert(pdf_path, output_dir))

    # ----------------------------------------------------------
    # 异步入口
    # ----------------------------------------------------------

    async def aconvert(self, pdf_path: str, output_dir: str) -> ConversionResult:
        """异步转换主流程"""
        start_time = time.time()
        metadata = ConversionMetadata()

        # 0. 检查文档级缓存
        pdf_hash = CacheManager.compute_pdf_hash(pdf_path)
        config_hash = CacheManager.compute_config_hash(self.config.model_dump())
        cached_doc = self.cache.get_document(pdf_hash, config_hash)
        if cached_doc:
            logger.info("Document cache hit, returning cached result")
            return ConversionResult(**cached_doc)

        # 1. 打开 PDF
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        metadata.total_pages = total_pages

        # 确定要处理的页码
        page_indices = self._get_page_indices(total_pages)

        self._report_progress(stage="detecting", total_pages=total_pages)

        # 2. 类型检测
        page_types = self.detector.classify(doc)
        for pt in page_types:
            metadata.page_types[pt.page_type.value] = (
                metadata.page_types.get(pt.page_type.value, 0) + 1
            )

        # 3. 分路处理：scanned/mixed → 渲染+检测+VLM, native → 直接提取
        all_processed: list[ProcessedBlock] = []
        page_heights: dict[int, int] = {}

        # 3a. 原生页面处理
        native_indices = [
            i for i in page_indices
            if page_types[i].page_type == PageType.NATIVE
        ]
        for idx in native_indices:
            page_num = idx + 1
            self._report_progress(
                stage=f"extracting native text: Page {page_num}",
                current_page=page_num,
                total_pages=total_pages,
            )
            native_blocks = await self._process_native_page(doc, idx, output_dir)
            all_processed.extend(native_blocks)

        # 3b. 扫描/混合页面 → 流水线并行
        scan_indices = [
            i for i in page_indices
            if page_types[i].page_type in (PageType.SCANNED, PageType.MIXED)
        ]

        if scan_indices:
            scanned_blocks, heights = await self._streaming_pipeline(
                doc, scan_indices, output_dir, metadata, total_pages,
            )
            all_processed.extend(scanned_blocks)
            page_heights.update(heights)

        # 3c. MIXED 页面的 fallback 区域
        mixed_indices = [
            i for i in page_indices
            if page_types[i].page_type == PageType.MIXED
        ]
        for idx in mixed_indices:
            native_content = self.native_extractor.extract(doc, idx)
            if native_content.needs_vlm_fallback:
                fallback_blocks = await self._process_fallback_regions(
                    doc, idx, native_content.needs_vlm_fallback, output_dir
                )
                all_processed.extend(fallback_blocks)

        # 4. 跨页合并
        self._report_progress(stage="merging cross-page elements")
        aggregator = CrossPageAggregator(page_heights=page_heights)
        all_processed = aggregator.detect_and_merge(all_processed)

        # 5. Markdown 组装
        self._report_progress(stage="assembling markdown")
        markdown = self.assembler.assemble(all_processed, output_dir)

        # 6. 生成元数据
        metadata.processing_time_seconds = time.time() - start_time

        # 保存 metadata
        import json
        from pathlib import Path
        meta_path = Path(output_dir) / "metadata.json"
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(
            json.dumps(metadata.__dict__, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

        result = ConversionResult(
            markdown=markdown,
            images=self._collect_images(output_dir),
            metadata=metadata,
            output_dir=output_dir,
        )

        # 缓存结果
        self.cache.set_document(pdf_hash, config_hash, {
            "markdown": result.markdown,
            "images": result.images,
            "metadata": metadata.__dict__,
            "output_dir": output_dir,
        })

        await self.vlm_engine.close()
        doc.close()

        return result

    # ----------------------------------------------------------
    # 流水线并行
    # ----------------------------------------------------------

    async def _streaming_pipeline(
        self,
        doc: fitz.Document,
        page_indices: list[int],
        output_dir: str,
        metadata: ConversionMetadata,
        total_pages: int,
    ) -> tuple[list[ProcessedBlock], dict[int, int]]:
        """渲染 → 布局检测 → VLM 的流水线并行"""
        max_queue = self.config.memory.max_cached_pages

        render_queue: asyncio.Queue[tuple[int, PageImage] | None] = asyncio.Queue(maxsize=max_queue)
        detect_queue: asyncio.Queue[tuple[int, PageImage, list[LayoutBlock]] | None] = asyncio.Queue(maxsize=max_queue)

        all_blocks: list[ProcessedBlock] = []
        page_heights: dict[int, int] = {}
        pdf_hash = CacheManager.compute_pdf_hash(doc.name) if doc.name else ""

        async def render_worker():
            for idx in page_indices:
                page_num = idx + 1
                self._report_progress(
                    stage=f"rendering: Page {page_num}",
                    current_page=page_num,
                    total_pages=total_pages,
                )
                pages = self.renderer.render_page(doc, idx)
                for page_img in pages:
                    # 预处理
                    result = self.preprocessor.preprocess(page_img.image)
                    page_img.image = result.image
                    page_img.width = result.image.width
                    page_img.height = result.image.height
                    page_heights[page_num] = page_img.height
                    await render_queue.put((page_num, page_img))
            await render_queue.put(None)

        async def detect_worker():
            while True:
                item = await render_queue.get()
                if item is None:
                    await detect_queue.put(None)
                    break
                page_num, page_img = item

                self._report_progress(
                    stage=f"layout detection: Page {page_num}",
                    current_page=page_num,
                    total_pages=total_pages,
                )

                # 检查布局缓存
                cached_layout = self.cache.get_layout(pdf_hash, page_num)
                if cached_layout:
                    blocks = [LayoutBlock(**b) for b in cached_layout]
                    metadata.cache_hits["layout"] = metadata.cache_hits.get("layout", 0) + 1
                else:
                    blocks = self.layout_detector.detect(page_img.image, page_number=page_num)
                    # 缓存布局结果
                    if pdf_hash:
                        layout_data = [
                            {
                                "block_type": b.block_type.value,
                                "bbox": b.bbox,
                                "confidence": b.confidence,
                                "reading_order": b.reading_order,
                                "page_number": b.page_number,
                                "column_id": b.column_id,
                            }
                            for b in blocks
                        ]
                        self.cache.set_layout(pdf_hash, page_num, layout_data)

                metadata.blocks_per_page[page_num] = len(blocks)
                await detect_queue.put((page_num, page_img, blocks))

        async def vlm_worker():
            fig_counters: dict[int, int] = {}
            table_counters: dict[int, int] = {}

            while True:
                item = await detect_queue.get()
                if item is None:
                    break
                page_num, page_img, blocks = item

                self._report_progress(
                    stage=f"VLM recognition: Page {page_num}",
                    current_page=page_num,
                    total_pages=total_pages,
                )

                # 分发
                dispatch = self.dispatcher.dispatch(page_img.image, page_num, blocks)

                # 保存图片
                fig_idx = fig_counters.get(page_num, 0)
                for crop in dispatch.image_crops:
                    fig_idx += 1
                    path = self.image_saver.save_image(crop, output_dir, fig_idx)
                    if path:
                        all_blocks.append(ProcessedBlock(
                            block_type=BlockType.IMAGE,
                            bbox=crop.bbox,
                            page_number=page_num,
                            image_path=path,
                            source="crop",
                        ))
                fig_counters[page_num] = fig_idx

                # 保存表格备份图片
                tbl_idx = table_counters.get(page_num, 0)
                for crop in dispatch.table_crops:
                    tbl_idx += 1
                    self.image_saver.save_table_backup(crop, output_dir, tbl_idx)
                table_counters[page_num] = tbl_idx

                # VLM 识别
                for vlm_req in dispatch.vlm_requests:
                    try:
                        results = await self.vlm_engine.process_request(vlm_req)
                        metadata.api_calls += 1

                        for res, (bbox, btype) in zip(results, vlm_req.regions):
                            # 坐标还原
                            if vlm_req.downsample_ratio < 1.0:
                                ratio = vlm_req.downsample_ratio
                                bbox = (
                                    int(bbox[0] / ratio),
                                    int(bbox[1] / ratio),
                                    int(bbox[2] / ratio),
                                    int(bbox[3] / ratio),
                                )

                            block = ProcessedBlock(
                                block_type=btype,
                                bbox=bbox,
                                page_number=page_num,
                                content=res.content,
                                content_type=res.content_type,
                                source="vlm",
                                validation_passed=res.validation_passed,
                                validation_warning=res.validation_warning,
                            )
                            all_blocks.append(block)

                    except Exception as e:
                        logger.error("VLM failed for page %d: %s", page_num, e)
                        metadata.errors.append(f"page {page_num}: {e}")
                        # 插入失败标记
                        for bbox, btype in vlm_req.regions:
                            all_blocks.append(ProcessedBlock(
                                block_type=btype,
                                bbox=bbox,
                                page_number=page_num,
                                content=f"[OCR_FAILED: page {page_num}]",
                                source="error",
                            ))

        await asyncio.gather(render_worker(), detect_worker(), vlm_worker())

        # 设置 reading_order
        page_blocks: dict[int, list[ProcessedBlock]] = {}
        for b in all_blocks:
            page_blocks.setdefault(b.page_number, []).append(b)
        for blocks in page_blocks.values():
            blocks.sort(key=lambda b: b.bbox[1])
            for i, b in enumerate(blocks):
                b.reading_order = i

        return all_blocks, page_heights

    # ----------------------------------------------------------
    # 原生页面处理
    # ----------------------------------------------------------

    async def _process_native_page(
        self, doc: fitz.Document, page_idx: int, output_dir: str
    ) -> list[ProcessedBlock]:
        """处理原生 PDF 页面"""
        content = self.native_extractor.extract(doc, page_idx)
        page_num = page_idx + 1
        blocks: list[ProcessedBlock] = []

        # 文本块
        for i, tb in enumerate(content.text_blocks):
            # 推断是否为标题（字号大/粗体）
            btype = BlockType.TEXT
            if tb.is_bold and tb.font_size > 14:
                btype = BlockType.TITLE
            elif tb.font_size > 16:
                btype = BlockType.TITLE

            blocks.append(ProcessedBlock(
                block_type=btype,
                bbox=tb.bbox,
                page_number=page_num,
                reading_order=i,
                content=tb.text,
                source="native",
            ))

        # 嵌入图片
        for i, img in enumerate(content.embedded_images):
            path = self.image_saver.save_embedded_image(
                img.image, page_num, i + 1, output_dir,
            )
            if path:
                blocks.append(ProcessedBlock(
                    block_type=BlockType.IMAGE,
                    bbox=img.bbox,
                    page_number=page_num,
                    image_path=path,
                    source="native",
                ))

        # 表格
        if content.tables:
            for table in content.tables:
                md_table = self._native_table_to_markdown(table.cells)
                blocks.append(ProcessedBlock(
                    block_type=BlockType.TABLE,
                    bbox=table.bbox,
                    page_number=page_num,
                    content=md_table,
                    content_type="markdown_table",
                    source="native",
                ))

        return blocks

    # ----------------------------------------------------------
    # Fallback 区域处理
    # ----------------------------------------------------------

    async def _process_fallback_regions(
        self, doc, page_idx, fallback_regions, output_dir,
    ) -> list[ProcessedBlock]:
        """处理 MIXED 页面的 VLM fallback 区域"""
        page_num = page_idx + 1
        pages = self.renderer.render_page(doc, page_idx)
        if not pages:
            return []

        page_img = pages[0]
        blocks: list[ProcessedBlock] = []

        for region in fallback_regions:
            btype = BlockType.FORMULA if region.reason == "formula" else BlockType.TEXT
            try:
                result = await self.vlm_engine.recognize(
                    page_img.image, region.bbox, btype
                )
                blocks.append(ProcessedBlock(
                    block_type=btype,
                    bbox=region.bbox,
                    page_number=page_num,
                    content=result.content,
                    content_type=result.content_type,
                    source="vlm_fallback",
                ))
            except Exception as e:
                logger.error("VLM fallback failed: %s", e)
                blocks.append(ProcessedBlock(
                    block_type=btype,
                    bbox=region.bbox,
                    page_number=page_num,
                    content=f"[OCR_FAILED: page {page_num}]",
                    source="error",
                ))

        return blocks

    # ----------------------------------------------------------
    # 成本预估
    # ----------------------------------------------------------

    def estimate(self, pdf_path: str) -> CostEstimate:
        """成本预估（dry-run）"""
        doc = fitz.open(pdf_path)
        page_types = self.detector.classify(doc)

        scanned_count = sum(
            1 for pt in page_types
            if pt.page_type in (PageType.SCANNED, PageType.MIXED)
        )
        native_count = sum(
            1 for pt in page_types if pt.page_type == PageType.NATIVE
        )

        # 估算: 每个扫描页约 6 个区域, 每 5 个区域合并为 1 次请求
        avg_regions_per_page = 6
        regions_per_request = self.config.vlm.max_regions_per_batch
        api_calls = scanned_count * avg_regions_per_page // regions_per_request

        # 估算成本 (以 Qwen VL 为参考, 约 5000 token/页, ¥0.035/请求)
        cost_per_call = 0.035
        estimated_cost = api_calls * cost_per_call

        # 估算时间
        time_per_call = 0.8  # 秒
        estimated_time = api_calls * time_per_call + len(page_types) * 0.3

        doc.close()

        return CostEstimate(
            total_pages=len(page_types),
            page_types={
                "scanned": scanned_count,
                "native": native_count,
                "mixed": sum(1 for pt in page_types if pt.page_type == PageType.MIXED),
            },
            estimated_api_calls=api_calls,
            estimated_cost_yuan=round(estimated_cost, 2),
            estimated_time_seconds=round(estimated_time, 1),
        )

    # ----------------------------------------------------------
    # 工具方法
    # ----------------------------------------------------------

    def _get_page_indices(self, total_pages: int) -> list[int]:
        if self.config.general.page_range:
            return [i - 1 for i in self.config.general.page_range if 1 <= i <= total_pages]
        return list(range(total_pages))

    @staticmethod
    def _native_table_to_markdown(cells: list[list[str]]) -> str:
        if not cells:
            return ""
        lines: list[str] = []
        # 表头
        header = "| " + " | ".join(cells[0]) + " |"
        lines.append(header)
        lines.append("| " + " | ".join("---" for _ in cells[0]) + " |")
        # 数据行
        for row in cells[1:]:
            lines.append("| " + " | ".join(row) + " |")
        return "\n".join(lines)

    @staticmethod
    def _collect_images(output_dir: str) -> list[dict[str, Any]]:
        from pathlib import Path
        images_dir = Path(output_dir) / "images"
        if not images_dir.exists():
            return []
        result = []
        for f in sorted(images_dir.iterdir()):
            if f.suffix.lower() in (".png", ".jpg", ".jpeg"):
                from PIL import Image
                with Image.open(f) as img:
                    result.append({
                        "filename": f.name,
                        "path": str(f),
                        "width": img.width,
                        "height": img.height,
                    })
        return result
