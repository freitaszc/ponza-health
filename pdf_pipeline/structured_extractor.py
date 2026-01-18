"""Higher level pipeline orchestrator for lab PDF analysis."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import fitz
import numpy as np
from PIL import Image
from tenacity import retry, stop_after_attempt, wait_exponential

from .file_utils import cleanup_files, derive_temp_path, ensure_directory
from .image_preprocess import ImagePreprocessor
from .layout import PdfLayoutExtractor
from .ocr import CompositeOcrBackend, OcrResult, TesseractBackend
from .reference_loader import load_references


@dataclass(slots=True)
class ExtractionConfig:
    ocr_required: bool = False
    temp_dir: Path = field(default_factory=lambda: Path("/tmp/ponza_pdf"))
    ocr_max_pages: int | None = None
    ocr_dpi: int = 300


@dataclass(slots=True)
class ExtractionArtifact:
    text: str
    blocks: List[str]
    ocr_confidence: float
    ocr_pages: int


@dataclass(slots=True)
class ExtractionResult:
    raw_text: str
    patient_data: dict
    lab_results: List[dict]
    suggestions: List[str]
    artifacts: ExtractionArtifact


class PdfAnalysisPipeline:
    def __init__(self, *, config: ExtractionConfig | None = None) -> None:
        self.config = config or ExtractionConfig()
        self.preprocessor = ImagePreprocessor()
        self.layout_extractor = PdfLayoutExtractor()
        self.ocr = CompositeOcrBackend([TesseractBackend()])

    @staticmethod
    def _open_document(source: str | bytes):
        if isinstance(source, (bytes, bytearray)):
            return fitz.open(stream=source, filetype="pdf")
        return fitz.open(source)  # type: ignore[arg-type]

    def extract(self, source: str | bytes, references_path: str | Path) -> ExtractionResult:
        references = load_references(references_path)
        blocks = self._extract_blocks(source)
        ocr_payload = self._maybe_run_ocr(source)
        raw_text = "\n".join(blocks)
        if ocr_payload:
            raw_text = "\n".join([raw_text, ocr_payload.text]).strip()

        from .structures import StructuredParser

        parser = StructuredParser(references)
        parsed = parser.parse(blocks=blocks, raw_text=raw_text)

        return ExtractionResult(
            raw_text=raw_text,
            patient_data=parsed.patient.model_dump(),
            lab_results=parsed.results,
            suggestions=parsed.suggestions,
            artifacts=ExtractionArtifact(
                text=ocr_payload.text if ocr_payload else "",
                blocks=blocks,
                ocr_confidence=ocr_payload.confidence if ocr_payload else 1.0,
                ocr_pages=ocr_payload.pages if ocr_payload else 0,
            ),
        )

    def _extract_blocks(self, source: str | bytes) -> List[str]:
        blocks = [b.text for b in self.layout_extractor.extract_blocks(source)]
        return [block for block in blocks if block]

    def _maybe_run_ocr(self, source: str | bytes) -> Optional[OcrResult]:
        if not self.config.ocr_required:
            return None
        max_pages = self.config.ocr_max_pages
        if max_pages is not None and max_pages <= 0:
            return None
        temp_dir = ensure_directory(self.config.temp_dir)
        page_images: List[Path] = []
        try:
            with self._open_document(source) as doc:
                page_count = doc.page_count
                if max_pages is not None:
                    page_count = min(page_count, max_pages)
                for page_number in range(page_count):
                    page = doc.load_page(page_number)
                    pix = page.get_pixmap(dpi=self.config.ocr_dpi)  # type: ignore[attr-defined]
                    img_bytes = pix.tobytes("png")
                    path = derive_temp_path(temp_dir, f"page_{page_number}", ".png")
                    path.write_bytes(img_bytes)
                    page_images.append(path)

            texts: List[str] = []
            for path in page_images:
                image = Image.open(path).convert("L")
                array = np.array(image)
                processed = self.preprocessor.run(array)
                processed_image = Image.fromarray(processed)
                result = self.ocr.extract_text(processed_image)
                texts.append(result.text)
            joined = "\n".join(texts).strip()
            if not joined:
                return OcrResult(text="", confidence=0.0, pages=len(page_images))
            avg_conf = 0.6 if texts else 0.0
            return OcrResult(text=joined, confidence=avg_conf, pages=len(page_images))
        finally:
            cleanup_files(page_images)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def run_pipeline(
    source: str | bytes,
    references_path: str | Path,
    *,
    require_ocr: bool = False,
    ocr_max_pages: int | None = None,
    ocr_dpi: int | None = None,
) -> ExtractionResult:
    config = ExtractionConfig(ocr_required=require_ocr)
    if ocr_max_pages is not None:
        config.ocr_max_pages = ocr_max_pages
    if ocr_dpi is not None:
        config.ocr_dpi = ocr_dpi
    pipeline = PdfAnalysisPipeline(config=config)
    return pipeline.extract(source, references_path)
