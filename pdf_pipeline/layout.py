"""Helpers for extracting structured text/layout information from PDFs."""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Iterable, List, Optional, Sequence

import pdfplumber


@dataclass(slots=True)
class TextBlock:
    text: str
    page_number: int
    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top


class PdfLayoutExtractor:
    def __init__(self, *, min_characters: int = 2) -> None:
        self.min_characters = min_characters

    @staticmethod
    def _open(source: str | bytes):
        if isinstance(source, (bytes, bytearray)):
            return pdfplumber.open(BytesIO(source))
        return pdfplumber.open(source)  # type: ignore[arg-type]

    def extract_blocks(self, path: str | bytes) -> List[TextBlock]:
        blocks: List[TextBlock] = []
        with self._open(path) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                for char_block in page.extract_words():
                    text = char_block.get("text", "").strip()
                    if len(text) < self.min_characters:
                        continue
                    blocks.append(
                        TextBlock(
                            text=text,
                            page_number=page_number,
                            left=char_block.get("x0", 0.0),
                            top=char_block.get("top", 0.0),
                            right=char_block.get("x1", 0.0),
                            bottom=char_block.get("bottom", 0.0),
                        )
                    )
        return blocks

    def extract_table(self, path: str | bytes, page_number: int) -> List[List[str]]:
        rows: List[List[str]] = []
        with self._open(path) as pdf:
            page = pdf.pages[page_number - 1]
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if not row or all(cell is None for cell in row):
                        continue
                    cleaned = [cell.strip() if isinstance(cell, str) else "" for cell in row]
                    rows.append(cleaned)
        return rows
