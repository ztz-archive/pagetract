# pagetract — 高精度 PDF 文档转 Markdown 系统

基于 **CV 布局检测 + VLM 全页理解** 的混合架构，将各类 PDF 文档高精度地转换为带图片引用的结构化 Markdown。

## 特性

- 🔍 **智能 PDF 类型检测**：自动识别扫描件/原生/混合 PDF，按需选择处理路径
- 📐 **精准布局检测**：可插拔 CV 模型（默认 DocLayout-YOLO），支持多栏检测与阅读顺序校正
- 🤖 **VLM 高精度识别**：整页图片 + 坐标提示，上下文完整，公式/表格/文字精度极高
- 🖼️ **图片提取**：自动提取并保存文档中的图片，支持 alt text 生成
- ⚡ **流水线并行**：渲染、检测、VLM 调用流水线并行，性能提升 77%
- 💾 **三层缓存**：布局/VLM/文档三层缓存，重复处理秒级返回
- 🌐 **API 服务**：FastAPI RESTful API + SSE 实时进度推送
- 🖥️ **Demo 网站**：Gradio 快速 Demo，支持逐页对比

## 快速开始

```bash
pip install pagetract

# 基本转换
pagetract convert input.pdf -o output/

# 启动 API 服务
pagetract serve

# 检查环境
pagetract doctor
```

## Python SDK

```python
from pagetract import PageTract

converter = PageTract(config_path="config.yaml")
result = converter.convert("input.pdf", output_dir="./output")
print(result.markdown)
```

## 配置

通过 `config.yaml` 或环境变量配置：

```bash
export SCANDOC_API_KEY="your-api-key"
pagetract config init  # 交互式初始化配置
```

## 许可证

MIT License
