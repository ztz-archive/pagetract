"""Gradio Demo — 快速可视化体验"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

DEMO_DESCRIPTION = """
# pagetract Demo

高精度 PDF 文档转 Markdown 系统。上传 PDF 文件，选择参数，点击转换。

基于 **CV 布局检测 + VLM 全页理解** 的混合架构。
"""

CUSTOM_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,500;0,8..60,600;0,8..60,700;1,8..60,400;1,8..60,500&display=swap');

:root {
    --heading-font: "Space Grotesk", "SF Pro Display", "Helvetica Neue", Arial, sans-serif;
    --body-font: "Source Serif 4", "Georgia", "Times New Roman", serif;
}

/* 标题：Space Grotesk（现代几何无衬线） */
h1, h2, h3, h4, h5, h6,
.gr-button, .tab-nav button, .label-wrap span {
    font-family: var(--heading-font) !important;
    letter-spacing: -0.01em;
}

/* 正文：Source Serif 4（过渡型衬线） */
body, p, span, li, td, th,
.prose, textarea, input,
.gr-textbox textarea, .gr-textbox input,
.markdown-text, .gr-markdown {
    font-family: var(--body-font) !important;
}

/* Markdown 渲染区域内标题 */
.gr-markdown h1, .gr-markdown h2, .gr-markdown h3,
.gr-markdown h4, .gr-markdown h5, .gr-markdown h6 {
    font-family: var(--heading-font) !important;
}

/* Markdown 渲染区域正文 */
.gr-markdown p, .gr-markdown li, .gr-markdown td {
    font-family: var(--body-font) !important;
    line-height: 1.65;
}
"""


def create_demo():
    """创建 Gradio Demo 界面"""
    import gradio as gr

    def convert_pdf(
        pdf_file,
        model: str,
        dpi: int,
        page_range: str,
        force_mode: str,
        api_key: str,
    ):
        """转换 PDF 文件"""
        if pdf_file is None:
            return "请上传 PDF 文件", "", "{}"

        from pagetract.config import load_config
        from pagetract.core.pipeline import Pipeline

        # 构建配置
        overrides: dict = {
            "vlm": {"model": model},
            "general": {"render_dpi": dpi},
            "render": {"render_dpi": dpi},
        }
        if api_key:
            overrides["vlm"]["api_key"] = api_key
        if force_mode and force_mode != "auto":
            overrides["pdf_detection"] = {"force_mode": force_mode}
        if page_range:
            from pagetract.cli import _parse_page_range
            overrides["general"]["page_range"] = _parse_page_range(page_range)

        config = load_config(overrides=overrides)
        pipeline = Pipeline(config)

        # 处理
        output_dir = tempfile.mkdtemp(prefix="pagetract_")

        try:
            result = pipeline.convert(pdf_file.name, output_dir)
            metadata = json.dumps(result.metadata.__dict__, indent=2, ensure_ascii=False, default=str)
            return result.markdown, result.markdown, metadata
        except Exception as e:
            return f"转换失败: {e}", "", "{}"

    def estimate_cost(pdf_file):
        """预估成本"""
        if pdf_file is None:
            return "请上传 PDF 文件"

        from pagetract.config import load_config
        from pagetract.core.pipeline import Pipeline

        config = load_config()
        pipeline = Pipeline(config)
        est = pipeline.estimate(pdf_file.name)

        return (
            f"总页数: {est.total_pages}\n"
            f"页面类型: {est.page_types}\n"
            f"预估 API 调用: {est.estimated_api_calls}\n"
            f"预估成本: ¥{est.estimated_cost_yuan:.2f}\n"
            f"预估耗时: {est.estimated_time_seconds:.1f}s"
        )

    with gr.Blocks(title="pagetract Demo", css=CUSTOM_CSS) as demo:
        gr.Markdown(DEMO_DESCRIPTION)

        with gr.Row():
            with gr.Column(scale=1):
                pdf_input = gr.File(
                    label="上传 PDF",
                    file_types=[".pdf"],
                    type="filepath",
                )
                with gr.Accordion("转换选项", open=False):
                    model_input = gr.Dropdown(
                        choices=["qwen3.5-plus"],
                        value="qwen3.5-plus",
                        label="VLM 模型",
                    )
                    dpi_input = gr.Slider(
                        minimum=150, maximum=600, value=300, step=50,
                        label="渲染 DPI",
                    )
                    page_range_input = gr.Textbox(
                        label="页码范围 (留空=全部)",
                        placeholder="例: 1-5,8,10",
                    )
                    force_mode_input = gr.Dropdown(
                        choices=["auto", "scanned", "native"],
                        value="auto",
                        label="强制模式",
                    )

                with gr.Accordion("设置", open=False):
                    api_key_input = gr.Textbox(
                        label="API Key (优先使用环境变量 SCANDOC_API_KEY)",
                        type="password",
                    )

                with gr.Row():
                    estimate_btn = gr.Button("成本预估", variant="secondary")
                    convert_btn = gr.Button("开始转换", variant="primary")

                estimate_output = gr.Textbox(label="预估结果", lines=5)

            with gr.Column(scale=2):
                with gr.Tabs():
                    with gr.TabItem("Markdown 渲染"):
                        md_rendered = gr.Markdown(label="渲染效果")
                    with gr.TabItem("Markdown 源码"):
                        md_source = gr.Textbox(
                            label="Markdown 源码",
                            lines=30,
                        )
                    with gr.TabItem("元数据"):
                        metadata_output = gr.Textbox(label="处理元数据", lines=20)

        # 绑定
        estimate_btn.click(
            fn=estimate_cost,
            inputs=[pdf_input],
            outputs=[estimate_output],
        )

        convert_btn.click(
            fn=convert_pdf,
            inputs=[
                pdf_input, model_input, dpi_input,
                page_range_input, force_mode_input, api_key_input,
            ],
            outputs=[md_rendered, md_source, metadata_output],
        )

    return demo


def launch_demo(port: int = 7860, share: bool = False):
    """启动 Demo"""
    import gradio as gr
    demo = create_demo()
    demo.launch(server_port=port, share=share, theme=gr.themes.Soft())


if __name__ == "__main__":
    launch_demo()
