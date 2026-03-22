"""模块G：页面预处理器 — 旋转校正、去倾斜、颜色反转检测"""

from __future__ import annotations

import logging

import numpy as np
from PIL import Image, ImageStat

from pagetract.config import PreprocessingConfig
from pagetract.models import PreprocessResult

logger = logging.getLogger(__name__)


class PagePreprocessor:
    """对扫描件/混合页面进行预处理"""

    def __init__(self, config: PreprocessingConfig | None = None):
        self.config = config or PreprocessingConfig()

    def preprocess(self, image: Image.Image) -> PreprocessResult:
        """依次执行: 1.旋转检测与校正 2.去倾斜 3.颜色反转检测"""
        rotation = 0
        skew = 0.0
        inverted = False

        # 1. 旋转校正 (90°/180°/270°)
        if self.config.enable_rotation_correction:
            image, rotation = self._correct_rotation(image)

        # 2. 倾斜校正 (微小角度)
        if self.config.enable_deskew:
            image, skew = self._correct_skew(image)

        # 3. 颜色反转检测
        if self.config.enable_inversion_detection:
            image, inverted = self._detect_and_fix_inversion(image)

        return PreprocessResult(
            image=image,
            rotation_applied=rotation,
            skew_corrected=skew,
            was_inverted=inverted,
        )

    # ----------------------------------------------------------
    # 旋转校正
    # ----------------------------------------------------------

    def _correct_rotation(self, image: Image.Image) -> tuple[Image.Image, int]:
        """检测并校正 90°/180°/270° 旋转。优先用 Tesseract OSD，回退到简单启发式。"""
        try:
            import pytesseract
            osd = pytesseract.image_to_osd(image)
            angle = 0
            for line in osd.split("\n"):
                if "Rotate:" in line:
                    angle = int(line.split(":")[-1].strip())
                    break
            if angle and angle in (90, 180, 270):
                logger.info("Rotation detected via Tesseract OSD: %d°", angle)
                return image.rotate(-angle, expand=True), angle
        except Exception:
            logger.debug("Tesseract OSD not available, using heuristic rotation detection")

        # 简易启发式：分析图片宽高比，检测是否旋转
        # 大多数文档页面高 > 宽，若宽 > 高*1.3 可能旋转了 90°
        w, h = image.size
        if w > h * 1.3:
            logger.info("Heuristic: wide image detected, rotating 90° CCW")
            return image.rotate(90, expand=True), 90

        return image, 0

    # ----------------------------------------------------------
    # 去倾斜
    # ----------------------------------------------------------

    def _correct_skew(self, image: Image.Image) -> tuple[Image.Image, float]:
        """使用 deskew 库或简单的 Hough 变换检测并修正微小倾斜"""
        try:
            from deskew import determine_skew
            img_array = np.array(image.convert("L"))
            angle = determine_skew(img_array)
            if angle is None:
                return image, 0.0
            if abs(angle) < self.config.deskew_threshold_degrees:
                return image, 0.0
            if abs(angle) > 10:
                # 倾斜角过大，可能检测错误
                logger.warning("Skew angle too large (%.1f°), skipping", angle)
                return image, 0.0
            logger.info("Deskew: correcting %.2f°", angle)
            rotated = image.rotate(angle, expand=True, fillcolor=(255, 255, 255))
            return rotated, angle
        except ImportError:
            logger.debug("deskew library not available")
            return image, 0.0
        except Exception as e:
            logger.warning("Deskew failed: %s", e)
            return image, 0.0

    # ----------------------------------------------------------
    # 颜色反转
    # ----------------------------------------------------------

    def _detect_and_fix_inversion(self, image: Image.Image) -> tuple[Image.Image, bool]:
        """检测白字黑底页面并反转"""
        gray = image.convert("L")
        stat = ImageStat.Stat(gray)
        mean_brightness = stat.mean[0]

        # 如果平均亮度 < 127, 页面主体为暗色 → 可能反转
        if mean_brightness < 100:
            logger.info("Color inversion detected (mean brightness=%.0f), inverting", mean_brightness)
            img_array = np.array(image)
            inverted = Image.fromarray(255 - img_array)
            return inverted, True

        return image, False
