"""Image preprocessing helpers to improve OCR throughput."""
from __future__ import annotations

from dataclasses import dataclass
import cv2
import numpy as np


@dataclass(slots=True)
class PreprocessOptions:
    deskew: bool = True
    denoise: bool = True
    adaptive_threshold: bool = True
    sharpen: bool = True


class ImagePreprocessor:
    """Run a configurable preprocess pipeline over page images."""

    def __init__(self, options: PreprocessOptions | None = None) -> None:
        self.options = options or PreprocessOptions()

    def run(self, image: np.ndarray) -> np.ndarray:
        result = image.copy()
        if self.options.denoise:
            result = self._denoise(result)
        if self.options.deskew:
            result = self._deskew(result)
        if self.options.adaptive_threshold:
            result = self._adaptive_threshold(result)
        if self.options.sharpen:
            result = self._sharpen(result)
        return result

    @staticmethod
    def _denoise(image: np.ndarray) -> np.ndarray:
        return cv2.fastNlMeansDenoising(image)

    @staticmethod
    def _deskew(image: np.ndarray) -> np.ndarray:
        coords = np.column_stack(np.where(image > 0))
        if coords.size == 0:
            return image
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle
        (h, w) = image.shape[:2]
        center = (w // 2, h // 2)
        m = cv2.getRotationMatrix2D(center, angle, 1.0)
        return cv2.warpAffine(image, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

    @staticmethod
    def _adaptive_threshold(image: np.ndarray) -> np.ndarray:
        return cv2.adaptiveThreshold(
            image,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            35,
            11,
        )

    @staticmethod
    def _sharpen(image: np.ndarray) -> np.ndarray:
        kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
        return cv2.filter2D(image, -1, kernel)
