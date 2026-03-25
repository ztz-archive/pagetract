"""视频处理模块 — B站视频音频转录 + VLM 视频理解"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

import httpx
from PIL import Image

from pagetract.config import VideoConfig, VLMConfig
from pagetract.models import VideoConversionResult

logger = logging.getLogger(__name__)


# ============================================================
# 工具函数
# ============================================================

def check_command(name: str) -> bool:
    """检查系统命令是否可用"""
    return shutil.which(name) is not None


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """运行子进程，统一错误处理"""
    logger.debug("Running: %s", " ".join(cmd))
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


# ============================================================
# 视频下载器
# ============================================================

class VideoDownloader:
    """使用 yt-dlp 下载 B站视频/音频"""

    def __init__(self, config: VideoConfig):
        self.config = config

    def get_info(self, url: str) -> dict[str, Any]:
        """获取视频元信息（标题、时长、UP主等）"""
        cmd = ["yt-dlp", "--dump-json", "--no-download", url]
        if self.config.cookies_from_browser:
            cmd.extend(["--cookies-from-browser", self.config.cookies_from_browser])

        result = _run(cmd, check=True)
        return json.loads(result.stdout)

    def download_audio(self, url: str, output_dir: str) -> Path:
        """仅下载音频"""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        template = str(out / "audio.%(ext)s")

        cmd = [
            "yt-dlp", "-x",
            "--audio-format", self.config.audio_format,
            "-o", template,
            url,
        ]
        if self.config.cookies_from_browser:
            cmd.extend(["--cookies-from-browser", self.config.cookies_from_browser])

        _run(cmd, check=True)
        return self._find_output(out, "audio")

    def download_video(self, url: str, output_dir: str) -> Path:
        """下载视频（限制分辨率控制文件大小）"""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        template = str(out / "video.%(ext)s")

        cmd = [
            "yt-dlp",
            "-f", "best[height<=720]/best",
            "-o", template,
            url,
        ]
        if self.config.cookies_from_browser:
            cmd.extend(["--cookies-from-browser", self.config.cookies_from_browser])

        _run(cmd, check=True)
        return self._find_output(out, "video")

    @staticmethod
    def _find_output(directory: Path, stem: str) -> Path:
        for f in directory.iterdir():
            if f.stem == stem and f.is_file():
                return f
        raise FileNotFoundError(f"Download failed: no '{stem}.*' found in {directory}")


# ============================================================
# 音频转录器
# ============================================================

class AudioTranscriber:
    """音频转文字 — 使用 OpenAI whisper-compatible STT API"""

    def __init__(self, video_config: VideoConfig, vlm_config: VLMConfig):
        self.config = video_config
        self.api_base = video_config.stt_api_base_url or vlm_config.api_base_url
        self.api_key = video_config.stt_api_key or vlm_config.api_key

    async def transcribe(self, audio_path: Path) -> list[dict[str, Any]]:
        """转录音频，返回分段结果 [{"index": 0, "text": "..."}, ...]"""
        chunks = await asyncio.to_thread(self._split_audio, audio_path)

        segments: list[dict[str, Any]] = []
        for i, chunk in enumerate(chunks):
            logger.info("Transcribing chunk %d/%d: %s", i + 1, len(chunks), chunk.name)
            text = await self._transcribe_chunk(chunk)
            if text.strip():
                segments.append({"index": i, "text": text.strip()})

        # 清理临时分片
        if len(chunks) > 1:
            for chunk in chunks:
                chunk.unlink(missing_ok=True)
            chunk_dir = chunks[0].parent
            if chunk_dir.name == "chunks":
                shutil.rmtree(chunk_dir, ignore_errors=True)

        return segments

    def _split_audio(self, audio_path: Path) -> list[Path]:
        """将长音频按 chunk_seconds 分片"""
        chunk_seconds = self.config.audio_chunk_seconds

        # 获取时长
        duration = self._get_duration(audio_path)
        if duration is None or duration <= chunk_seconds:
            return [audio_path]

        chunk_dir = audio_path.parent / "chunks"
        chunk_dir.mkdir(exist_ok=True)

        chunks: list[Path] = []
        num_chunks = int(duration / chunk_seconds) + 1
        for i in range(num_chunks):
            start = i * chunk_seconds
            chunk_path = chunk_dir / f"chunk_{i:04d}{audio_path.suffix}"
            result = _run([
                "ffmpeg", "-y", "-i", str(audio_path),
                "-ss", str(start), "-t", str(chunk_seconds),
                "-acodec", "copy", str(chunk_path),
            ])
            if result.returncode == 0 and chunk_path.exists() and chunk_path.stat().st_size > 0:
                chunks.append(chunk_path)

        return chunks if chunks else [audio_path]

    @staticmethod
    def _get_duration(path: Path) -> float | None:
        """用 ffprobe 获取音频时长"""
        result = _run([
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ])
        if result.returncode == 0:
            try:
                return float(result.stdout.strip())
            except ValueError:
                pass
        return None

    async def _transcribe_chunk(self, audio_path: Path) -> str:
        """调用 STT API 转录单个音频段"""
        url = f"{self.api_base.rstrip('/')}/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        async with httpx.AsyncClient(timeout=180.0) as client:
            with open(audio_path, "rb") as f:
                resp = await client.post(
                    url,
                    headers=headers,
                    files={"file": (audio_path.name, f, "audio/mpeg")},
                    data={"model": self.config.stt_model},
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("text", "")


# ============================================================
# 关键帧提取器
# ============================================================

class VideoFrameExtractor:
    """从视频中提取关键帧"""

    def __init__(self, config: VideoConfig):
        self.config = config

    def extract(self, video_path: Path) -> list[Image.Image]:
        """提取等间距关键帧"""
        duration = self._get_duration(video_path)
        if duration is None or duration <= 0:
            logger.error("Cannot determine video duration for %s", video_path)
            return []

        interval = self.config.frame_interval_seconds
        max_frames = self.config.max_key_frames

        # 计算时间戳
        timestamps: list[float] = []
        t = 0.0
        while t < duration and len(timestamps) < max_frames:
            timestamps.append(t)
            t += interval

        if not timestamps:
            timestamps = [0.0]

        # 用 ffmpeg 逐帧提取
        frames: list[Image.Image] = []
        with tempfile.TemporaryDirectory() as tmpdir:
            for i, ts in enumerate(timestamps):
                frame_path = Path(tmpdir) / f"frame_{i:04d}.jpg"
                result = _run([
                    "ffmpeg", "-y",
                    "-ss", str(ts),
                    "-i", str(video_path),
                    "-vframes", "1",
                    "-q:v", "2",
                    str(frame_path),
                ])
                if result.returncode == 0 and frame_path.exists():
                    img = Image.open(frame_path).copy()
                    frames.append(img)

        logger.info(
            "Extracted %d key frames from video (duration=%.1fs, interval=%ds)",
            len(frames), duration, interval,
        )
        return frames

    @staticmethod
    def _get_duration(path: Path) -> float | None:
        result = _run([
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ])
        if result.returncode == 0:
            try:
                return float(result.stdout.strip())
            except ValueError:
                pass
        return None


# ============================================================
# VLM 视频理解
# ============================================================

class VideoUnderstanderVLM:
    """使用 VLM 分析视频关键帧，生成结构化理解"""

    def __init__(self, video_config: VideoConfig, vlm_config: VLMConfig):
        self.config = video_config
        self.vlm_config = vlm_config

    async def understand(
        self, frames: list[Image.Image], video_info: dict[str, Any],
    ) -> str:
        """将关键帧发送给 VLM，获取视频理解结果"""
        if not frames:
            return ""

        model = self.config.video_model or self.vlm_config.model
        api_base = self.vlm_config.api_base_url
        api_key = self.vlm_config.api_key

        # 构建多图消息
        content: list[dict[str, Any]] = []
        for frame in frames:
            b64 = self._image_to_base64(frame)
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            })

        # 构建 prompt
        title = video_info.get("title", "未知")
        description = video_info.get("description", "")
        duration = video_info.get("duration", 0)

        prompt_text = self.config.understanding_prompt.format(
            title=title,
            description=description,
            duration=duration,
            num_frames=len(frames),
        )
        content.append({"type": "text", "text": prompt_text})

        # 调用 VLM
        url = f"{api_base.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "temperature": 0.3,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": 8192,
        }

        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("VLM returned empty response for video understanding")

        return choices[0]["message"]["content"]

    @staticmethod
    def _image_to_base64(image: Image.Image) -> str:
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode("utf-8")


# ============================================================
# 视频处理器（主编排）
# ============================================================

class VideoProcessor:
    """视频处理器 — 编排音频转录和视频理解双路径"""

    def __init__(self, video_config: VideoConfig, vlm_config: VLMConfig):
        self.config = video_config
        self.vlm_config = vlm_config
        self.downloader = VideoDownloader(video_config)
        self.transcriber = AudioTranscriber(video_config, vlm_config)
        self.frame_extractor = VideoFrameExtractor(video_config)
        self.understander = VideoUnderstanderVLM(video_config, vlm_config)
        self._progress_callback: Callable[[dict[str, Any]], None] | None = None

    def set_progress_callback(self, callback: Callable[[dict[str, Any]], None]) -> None:
        self._progress_callback = callback

    def _report(self, stage: str, **extra: Any) -> None:
        if self._progress_callback:
            self._progress_callback({"stage": stage, **extra})

    # ----------------------------------------------------------
    # 主流程
    # ----------------------------------------------------------

    async def process(
        self,
        url: str,
        output_dir: str,
        audio_only: bool = False,
        video_only: bool = False,
    ) -> VideoConversionResult:
        """处理B站视频：音频转录 + 视频理解 → 两份 Markdown"""
        self._check_dependencies()

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        download_dir = Path(self.config.download_dir)
        download_dir.mkdir(parents=True, exist_ok=True)

        # 1) 获取视频元信息
        self._report("获取视频信息...")
        video_info = await asyncio.to_thread(self.downloader.get_info, url)
        title = video_info.get("title", "untitled")
        logger.info("Video: %s (duration=%ss)", title, video_info.get("duration", "?"))

        result = VideoConversionResult(
            video_info=video_info,
            output_dir=str(output_path),
        )

        # 2) 音频转录路径
        if not video_only:
            result = await self._process_audio(url, download_dir, output_path, video_info, result)

        # 3) 视频理解路径
        if not audio_only:
            result = await self._process_video(url, download_dir, output_path, video_info, result)

        return result

    # ----------------------------------------------------------
    # 音频转录路径
    # ----------------------------------------------------------

    async def _process_audio(
        self,
        url: str,
        download_dir: Path,
        output_path: Path,
        video_info: dict[str, Any],
        result: VideoConversionResult,
    ) -> VideoConversionResult:
        self._report("下载音频...")
        audio_path = await asyncio.to_thread(
            self.downloader.download_audio, url, str(download_dir),
        )

        self._report("音频转文字...")
        segments = await self.transcriber.transcribe(audio_path)

        transcript_text = "\n\n".join(seg["text"] for seg in segments)

        audio_md = self._format_audio_markdown(url, video_info, transcript_text)
        result.audio_markdown = audio_md

        md_path = output_path / "audio_transcript.md"
        md_path.write_text(audio_md, encoding="utf-8")
        result.audio_markdown_path = str(md_path)

        self._report("音频转录完成")
        logger.info("Audio transcript saved to %s", md_path)
        return result

    # ----------------------------------------------------------
    # 视频理解路径
    # ----------------------------------------------------------

    async def _process_video(
        self,
        url: str,
        download_dir: Path,
        output_path: Path,
        video_info: dict[str, Any],
        result: VideoConversionResult,
    ) -> VideoConversionResult:
        self._report("下载视频...")
        video_path = await asyncio.to_thread(
            self.downloader.download_video, url, str(download_dir),
        )

        self._report("提取关键帧...")
        frames = await asyncio.to_thread(self.frame_extractor.extract, video_path)

        self._report(f"VLM 视频理解（{len(frames)} 帧）...")
        understanding = await self.understander.understand(frames, video_info)

        video_md = self._format_video_markdown(url, video_info, understanding, len(frames))
        result.video_markdown = video_md

        md_path = output_path / "video_understanding.md"
        md_path.write_text(video_md, encoding="utf-8")
        result.video_markdown_path = str(md_path)

        self._report("视频理解完成")
        logger.info("Video understanding saved to %s", md_path)
        return result

    # ----------------------------------------------------------
    # Markdown 格式化
    # ----------------------------------------------------------

    @staticmethod
    def _format_audio_markdown(
        url: str, info: dict[str, Any], transcript: str,
    ) -> str:
        title = info.get("title", "未知")
        uploader = info.get("uploader", "未知")
        duration = info.get("duration", 0)
        minutes, seconds = divmod(int(duration), 60)

        lines = [
            f"# {title} — 音频转录",
            "",
            f"> 视频来源：{url}",
            f"> UP主：{uploader}",
            f"> 时长：{minutes}分{seconds}秒",
            "",
            "---",
            "",
            transcript,
            "",
        ]
        return "\n".join(lines)

    @staticmethod
    def _format_video_markdown(
        url: str, info: dict[str, Any], understanding: str, num_frames: int,
    ) -> str:
        title = info.get("title", "未知")
        uploader = info.get("uploader", "未知")
        duration = info.get("duration", 0)
        minutes, seconds = divmod(int(duration), 60)

        lines = [
            f"# {title} — 视频理解",
            "",
            f"> 视频来源：{url}",
            f"> UP主：{uploader}",
            f"> 时长：{minutes}分{seconds}秒",
            f"> 分析帧数：{num_frames}",
            "",
            "---",
            "",
            understanding,
            "",
        ]
        return "\n".join(lines)

    # ----------------------------------------------------------
    # 依赖检查
    # ----------------------------------------------------------

    @staticmethod
    def _check_dependencies() -> None:
        missing = []
        if not check_command("yt-dlp"):
            missing.append("yt-dlp")
        if not check_command("ffmpeg"):
            missing.append("ffmpeg")
        if not check_command("ffprobe"):
            missing.append("ffprobe")
        if missing:
            raise RuntimeError(
                f"Missing required commands: {', '.join(missing)}. "
                "Install them first:\n"
                "  pip install yt-dlp\n"
                "  Download ffmpeg from https://ffmpeg.org/download.html"
            )
