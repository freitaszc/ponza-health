"""Centralized helpers for loading and querying lab reference data."""
from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from difflib import get_close_matches
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping


def _normalize(label: str) -> str:
    normalized = unicodedata.normalize("NFKD", label or "")
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    lowered = stripped.lower()
    return " ".join(lowered.split())


@dataclass(slots=True)
class ReferenceEntry:
    name: str
    data: Mapping[str, Any]

    def ideal_for(self, gender: str | None) -> Any:
        ideal = self.data.get("ideal") if isinstance(self.data, Mapping) else None
        if isinstance(ideal, Mapping) and gender:
            variants = (
                gender,
                gender.upper(),
                gender.lower(),
                gender.title(),
            )
            for variant in variants:
                if variant in ideal:
                    return ideal[variant]
        return ideal

    def medications_for(self, status: str) -> Any:
        meds = self.data.get("medications") if isinstance(self.data, Mapping) else None
        if isinstance(meds, Mapping):
            return meds.get(status)
        return meds


@dataclass(slots=True)
class ReferenceData:
    entries: Mapping[str, ReferenceEntry]
    normalized_keys: Mapping[str, str]

    def best_match(self, name: str) -> ReferenceEntry | None:
        if not name:
            return None
        key_norm = _normalize(name)
        
        # Exact match first
        mapped = self.normalized_keys.get(key_norm)
        if mapped:
            return self.entries.get(mapped)
        
        # Try fuzzy matching with more lenient cutoff
        # Start with strict matching, then relax
        for cutoff in [0.85, 0.80, 0.75, 0.70]:
            matches = get_close_matches(key_norm, self.normalized_keys.keys(), n=1, cutoff=cutoff)
            if matches:
                mapped = self.normalized_keys.get(matches[0])
                if mapped:
                    return self.entries.get(mapped)
        
        return None

    def get_medications(self, test_name: str, status: str) -> Any:
        entry = self.best_match(test_name)
        if not entry:
            return None
        return entry.medications_for(status)


@lru_cache(maxsize=4)
def load_references(path: str | Path) -> ReferenceData:
    raw = Path(path)
    payload = json.loads(raw.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise TypeError("Arquivo de referências deve ser um objeto JSON")
    candidate = payload.get("tests") if isinstance(payload.get("tests"), Mapping) else None
    tests = candidate or payload
    entries: dict[str, ReferenceEntry] = {}
    normalized_keys: dict[str, str] = {}
    for name, data in tests.items():
        if not isinstance(data, Mapping):
            continue
        entries[name] = ReferenceEntry(name=name, data=data)
        normalized_keys[_normalize(name)] = name
    return ReferenceData(entries=entries, normalized_keys=normalized_keys)
