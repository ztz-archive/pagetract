"""启动 Gradio Demo

用法:
    python run_demo.py
    python run_demo.py --port 7860
    python run_demo.py --share    # 生成公网链接
"""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="启动 pagetract Gradio Demo")
    parser.add_argument("--port", type=int, default=7860, help="监听端口 (默认: 7860)")
    parser.add_argument("--share", action="store_true", help="生成 Gradio 公网分享链接")
    args = parser.parse_args()

    try:
        import gradio  # noqa: F401
    except ImportError:
        print("错误: 缺少 gradio，请先安装 Demo 依赖:")
        print("  pip install -e \".[demo]\"")
        sys.exit(1)

    from pagetract.demo.gradio_app import launch_demo

    print(f"╭──────────────────────────────────────────╮")
    print(f"│  pagetract Gradio Demo                   │")
    print(f"│  地址: http://localhost:{args.port}           │")
    print(f"│  按 Ctrl+C 停止                          │")
    print(f"╰──────────────────────────────────────────╯")

    launch_demo(port=args.port, share=args.share)


if __name__ == "__main__":
    main()
