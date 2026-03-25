"""视频处理模块测试"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pagetract.config import VideoConfig, VLMConfig
from pagetract.models import VideoConversionResult


# ============================================================
# VideoConfig 测试
# ============================================================

class TestVideoConfig:
    def test_defaults(self):
        cfg = VideoConfig()
        assert cfg.download_dir == "./cache/video"
        assert cfg.stt_model == "sensevoice-v1"
        assert cfg.audio_format == "mp3"
        assert cfg.audio_chunk_seconds == 600
        assert cfg.max_key_frames == 20
        assert cfg.frame_interval_seconds == 30
        assert cfg.cookies_from_browser is None

    def test_custom_values(self):
        cfg = VideoConfig(
            stt_model="whisper-1",
            max_key_frames=10,
            frame_interval_seconds=60,
        )
        assert cfg.stt_model == "whisper-1"
        assert cfg.max_key_frames == 10
        assert cfg.frame_interval_seconds == 60


# ============================================================
# VideoConversionResult 测试
# ============================================================

class TestVideoConversionResult:
    def test_defaults(self):
        result = VideoConversionResult()
        assert result.audio_markdown == ""
        assert result.video_markdown == ""
        assert result.video_info == {}
        assert result.output_dir == ""
        assert result.audio_markdown_path == ""
        assert result.video_markdown_path == ""

    def test_with_data(self):
        result = VideoConversionResult(
            audio_markdown="# Test\n\nHello",
            video_markdown="# Test\n\nWorld",
            video_info={"title": "Test Video", "duration": 120},
            output_dir="./output",
            audio_markdown_path="./output/audio_transcript.md",
            video_markdown_path="./output/video_understanding.md",
        )
        assert result.video_info["title"] == "Test Video"
        assert result.video_info["duration"] == 120


# ============================================================
# VideoDownloader 测试
# ============================================================

class TestVideoDownloader:
    def test_get_info(self):
        from pagetract.core.video_processor import VideoDownloader

        dl = VideoDownloader(VideoConfig())
        fake_info = {"title": "Test", "duration": 60, "uploader": "tester"}

        with patch("pagetract.core.video_processor._run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout=json.dumps(fake_info), returncode=0,
            )
            info = dl.get_info("https://bilibili.com/video/BV1234")

        assert info["title"] == "Test"
        assert info["duration"] == 60

    def test_get_info_with_cookies(self):
        from pagetract.core.video_processor import VideoDownloader

        cfg = VideoConfig(cookies_from_browser="chrome")
        dl = VideoDownloader(cfg)

        with patch("pagetract.core.video_processor._run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout='{"title":"test"}', returncode=0,
            )
            dl.get_info("https://bilibili.com/video/BV1234")

        call_args = mock_run.call_args[0][0]
        assert "--cookies-from-browser" in call_args
        assert "chrome" in call_args


# ============================================================
# AudioTranscriber 测试
# ============================================================

class TestAudioTranscriber:
    def test_uses_vlm_config_fallback(self):
        from pagetract.core.video_processor import AudioTranscriber

        video_cfg = VideoConfig()  # stt_api_base_url and stt_api_key are empty
        vlm_cfg = VLMConfig(
            api_base_url="https://test.api.com/v1",
            api_key="test-key",
        )
        transcriber = AudioTranscriber(video_cfg, vlm_cfg)
        assert transcriber.api_base == "https://test.api.com/v1"
        assert transcriber.api_key == "test-key"

    def test_uses_explicit_stt_config(self):
        from pagetract.core.video_processor import AudioTranscriber

        video_cfg = VideoConfig(
            stt_api_base_url="https://stt.api.com/v1",
            stt_api_key="stt-key",
        )
        vlm_cfg = VLMConfig(api_base_url="https://vlm.api.com/v1", api_key="vlm-key")
        transcriber = AudioTranscriber(video_cfg, vlm_cfg)
        assert transcriber.api_base == "https://stt.api.com/v1"
        assert transcriber.api_key == "stt-key"


# ============================================================
# VideoFrameExtractor 测试
# ============================================================

class TestVideoFrameExtractor:
    def test_timestamp_calculation(self):
        from pagetract.core.video_processor import VideoFrameExtractor

        cfg = VideoConfig(max_key_frames=5, frame_interval_seconds=10)
        extractor = VideoFrameExtractor(cfg)

        # 模拟40秒视频
        with patch.object(extractor, "_get_duration", return_value=40.0):
            with patch("pagetract.core.video_processor._run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1)  # ffmpeg fails → no frames
                frames = extractor.extract(Path("fake.mp4"))

        # 应该尝试提取4帧 (0, 10, 20, 30) 但ffmpeg失败所以为空
        assert frames == []
        assert mock_run.call_count == 4


# ============================================================
# VideoProcessor Markdown格式化测试
# ============================================================

class TestVideoProcessorFormat:
    def test_format_audio_markdown(self):
        from pagetract.core.video_processor import VideoProcessor

        info = {"title": "Python教程", "uploader": "UP主", "duration": 185}
        md = VideoProcessor._format_audio_markdown(
            "https://bilibili.com/video/BV123", info, "大家好，今天讲Python。"
        )
        assert "Python教程" in md
        assert "音频转录" in md
        assert "UP主" in md
        assert "3分5秒" in md
        assert "大家好" in md

    def test_format_video_markdown(self):
        from pagetract.core.video_processor import VideoProcessor

        info = {"title": "数据分析", "uploader": "UP主", "duration": 300}
        md = VideoProcessor._format_video_markdown(
            "https://bilibili.com/video/BV456", info, "视频展示了数据分析流程。", 10
        )
        assert "数据分析" in md
        assert "视频理解" in md
        assert "分析帧数：10" in md
        assert "5分0秒" in md


# ============================================================
# check_command 测试
# ============================================================

class TestCheckCommand:
    def test_check_existing_command(self):
        from pagetract.core.video_processor import check_command

        # python should always exist
        assert check_command("python") or check_command("python3")

    def test_check_nonexistent_command(self):
        from pagetract.core.video_processor import check_command

        assert not check_command("nonexistent_command_12345")


# ============================================================
# PagetractConfig 集成测试
# ============================================================

class TestConfigIntegration:
    def test_config_has_video_section(self):
        from pagetract.config import PagetractConfig

        cfg = PagetractConfig()
        assert hasattr(cfg, "video")
        assert isinstance(cfg.video, VideoConfig)
        assert cfg.video.stt_model == "sensevoice-v1"

    def test_config_load_with_video_overrides(self):
        from pagetract.config import load_config

        cfg = load_config(overrides={"video": {"max_key_frames": 10}})
        assert cfg.video.max_key_frames == 10
