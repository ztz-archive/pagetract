"""启动 API 服务

用法:
    python run_api.py
    python run_api.py --port 9000
    python run_api.py --host 127.0.0.1 --port 8080
"""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="启动 pagetract API 服务")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址 (默认: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=34045, help="监听端口 (默认: 34045)")
    parser.add_argument("--config", default=None, help="配置文件路径")
    parser.add_argument("--reload", action="store_true", help="开发模式：文件变更时自动重载")
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError:
        print("错误: 缺少 uvicorn，请先安装 API 依赖:")
        print("  pip install -e \".[api]\"")
        sys.exit(1)

    from pagetract.config import load_config
    from pagetract.api.app import create_app

    overrides = {"api": {"host": args.host, "port": args.port}}
    config = load_config(config_path=args.config, overrides=overrides)
    app = create_app(config)

    print(f"╭──────────────────────────────────────────╮")
    print(f"│  pagetract API 服务                      │")
    print(f"│  地址: http://{args.host}:{args.port}         │")
    print(f"│  文档: http://{args.host}:{args.port}/docs    │")
    print(f"│  按 Ctrl+C 停止                          │")
    print(f"╰──────────────────────────────────────────╯")

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
