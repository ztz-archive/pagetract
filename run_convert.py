"""快速转换 PDF — 脚本方式调用 SDK

用法:
    python run_convert.py input.pdf
    python run_convert.py input.pdf -o output/
    python run_convert.py input.pdf --model gpt-4o --dpi 400
    python run_convert.py input.pdf --dry-run    # 仅预估成本
    python run_convert.py input.pdf --pages 1-5
"""

import argparse
import sys
import os


def main():
    parser = argparse.ArgumentParser(description="pagetract — PDF 转 Markdown")
    parser.add_argument("input", help="PDF 文件路径")
    parser.add_argument("-o", "--output", default="./output", help="输出目录 (默认: ./output)")
    parser.add_argument("--config", default=None, help="配置文件路径")
    parser.add_argument("--model", default=None, help="VLM 模型名")
    parser.add_argument("--dpi", type=int, default=None, help="渲染 DPI")
    parser.add_argument("--pages", default=None, help="页码范围 (如: 1-5,8,10)")
    parser.add_argument("--force-mode", default=None, choices=["scanned", "native"], help="强制模式")
    parser.add_argument("--dry-run", action="store_true", help="仅预估成本，不转换")
    parser.add_argument("--no-cache", action="store_true", help="禁用缓存")
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"错误: 文件不存在 — {args.input}")
        sys.exit(1)

    from pagetract.config import load_config
    from pagetract.core.pipeline import Pipeline

    # 构建配置
    overrides: dict = {}
    if args.model:
        overrides.setdefault("vlm", {})["model"] = args.model
    if args.dpi:
        overrides.setdefault("render", {})["render_dpi"] = args.dpi
    if args.force_mode:
        overrides.setdefault("pdf_detection", {})["force_mode"] = args.force_mode
    if args.no_cache:
        overrides.setdefault("cache", {})["enable"] = False
    if args.pages:
        page_list = _parse_page_range(args.pages)
        overrides.setdefault("general", {})["page_range"] = page_list

    config = load_config(config_path=args.config, overrides=overrides or None)
    pipeline = Pipeline(config)

    # Dry-run: 仅预估
    if args.dry_run:
        est = pipeline.estimate(args.input)
        print(f"总页数:       {est.total_pages}")
        print(f"页面类型:     {est.page_types}")
        print(f"预估 API 调用: {est.estimated_api_calls}")
        print(f"预估成本:     ¥{est.estimated_cost_yuan:.2f}")
        print(f"预估耗时:     {est.estimated_time_seconds:.1f}s")
        return

    # 执行转换
    print(f"处理中: {args.input}")
    result = pipeline.convert(args.input, args.output)

    meta = result.metadata
    print(f"\n转换完成!")
    print(f"  输出目录:   {args.output}")
    print(f"  图片数量:   {len(result.images)}")
    print(f"  处理耗时:   {meta.processing_time_seconds:.1f}s")
    print(f"  API 调用:   {meta.api_calls}")
    print(f"  预估成本:   ¥{meta.estimated_cost_yuan:.2f}")
    if meta.errors:
        print(f"  错误:       {len(meta.errors)} 个")
        for e in meta.errors[:5]:
            print(f"    - {e}")


def _parse_page_range(pages_str: str) -> list[int]:
    result: list[int] = []
    for part in pages_str.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            result.extend(range(int(start), int(end) + 1))
        else:
            result.append(int(part))
    return sorted(set(result))


if __name__ == "__main__":
    main()
