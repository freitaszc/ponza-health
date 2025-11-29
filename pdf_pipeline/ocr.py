"""OCR wrapper that can switch between different providers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

import pytesseract
from PIL import Image


@dataclass(slots=True)
class OcrResult:
    text: str
    confidence: float
    language: str | None = None
    pages: int = 0


class OcrBackend(Protocol):
    def extract_text(self, image: Image.Image) -> OcrResult:
        ...


class TesseractBackend:
    """Thin wrapper around pytesseract for consistent configuration."""

    def __init__(self, language: str = "por+eng", psm: int = 6, oem: int = 1) -> None:
        self.language = language
        self.psm = psm
        self.oem = oem

    def extract_text(self, image: Image.Image) -> OcrResult:
        config = f"--psm {self.psm} --oem {self.oem}"
        text = pytesseract.image_to_string(image, lang=self.language, config=config)
        return OcrResult(text=text, confidence=0.6, language=self.language)


class CompositeOcrBackend:
    """Run several backends until one returns non-empty text."""

    def __init__(self, backends: Sequence[OcrBackend]) -> None:
        self.backends = tuple(backends)

    def extract_text(self, image: Image.Image) -> OcrResult:
        for backend in self.backends:
            result = backend.extract_text(image)
            if result.text.strip():
                return result
        return OcrResult(text="", confidence=0.0, pages=0)
