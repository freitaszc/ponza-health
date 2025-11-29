"""Domain models for structured PDF parsing."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence

from pydantic import BaseModel, Field

from .reference_loader import ReferenceData


class PatientInfo(BaseModel):
    name: str | None = None
    doctor: str | None = None
    gender: str | None = None
    birth_date: str | None = None
    phone: str | None = None
    cpf: str | None = None


class LabResult(BaseModel):
    test: str = Field(..., alias="name")
    value: float | None = None
    unit: str | None = None
    reference: str | None = None
    status: str | None = None


@dataclass(slots=True)
class ParserOutput:
    patient: PatientInfo
    results: List[Dict]
    suggestions: List[str]


class StructuredParser:
    def __init__(self, references: ReferenceData) -> None:
        self.references = references

    def parse(self, *, blocks: Sequence[str], raw_text: str) -> ParserOutput:
        patient = self._extract_patient(blocks)
        results = self._extract_results(blocks, raw_text, patient.gender)
        suggestions = self._build_suggestions(results)
        return ParserOutput(
            patient=patient,
            results=[r.model_dump(by_alias=True) for r in results],
            suggestions=suggestions,
        )

    def _extract_patient(self, blocks: Sequence[str]) -> PatientInfo:
        name = next((b for b in blocks if b.lower().startswith("paciente")), None)
        if name:
            _, _, name_value = name.partition(":")
        else:
            name_value = None
        doctor = next((b for b in blocks if "médico" in b.lower() or "solicitante" in b.lower()), None)
        doctor_value = None
        if doctor and ":" in doctor:
            doctor_value = doctor.split(":", 1)[-1].strip()
        gender = next((b for b in blocks if "sexo" in b.lower()), None)
        if gender and ":" in gender:
            gender = gender.split(":", 1)[-1].strip()
        birth = next((b for b in blocks if "nascimento" in b.lower()), None)
        if birth and ":" in birth:
            birth = birth.split(":", 1)[-1].strip()
        phone = next((b for b in blocks if "telefone" in b.lower()), None)
        if phone and ":" in phone:
            phone = phone.split(":", 1)[-1].strip()
        cpf = next((b for b in blocks if "cpf" in b.lower()), None)
        if cpf and ":" in cpf:
            cpf = cpf.split(":", 1)[-1].strip()
        return PatientInfo(
            name=name_value.strip() if name_value else None,
            doctor=doctor_value,
            gender=gender,
            birth_date=birth,
            phone=phone,
            cpf=cpf,
        )

    def _extract_results(self, blocks: Sequence[str], raw_text: str, gender: str | None) -> List[LabResult]:
        results: List[LabResult] = []
        for block in blocks:
            if ":" not in block:
                continue
            name, value = [part.strip() for part in block.split(":", 1)]
            if not name or not value:
                continue
            if name.lower().startswith("paciente"):
                continue
            entry = self.references.best_match(name)
            ref = entry.ideal_for(gender) if entry else None
            status = None
            numeric_value = None
            try:
                numeric_value = float(value.replace(",", "."))
            except Exception:
                continue
            min_val, max_val = self._parse_range(ref) if ref else (None, None)
            if min_val is not None and numeric_value < min_val:
                status = "low"
            elif max_val is not None and numeric_value > max_val:
                status = "high"
            else:
                status = "normal"
            results.append(
                LabResult(
                    name=entry.name if entry else name,
                    value=numeric_value,
                    unit=None,
                    reference=str(ref) if ref else None,
                    status=status,
                )
            )
        return results

    def _parse_range(self, ref: str | None) -> tuple[float | None, float | None]:
        if not ref:
            return None, None
        try:
            parts = ref.replace(",", ".").split("-")
            if len(parts) == 2:
                return float(parts[0].strip()), float(parts[1].strip())
        except ValueError:
            return None, None
        return None, None

    def _build_suggestions(self, results: Sequence[LabResult]) -> List[str]:
        suggestions: List[str] = []
        for result in results:
            if result.status == "low":
                med = self.references.get_medications(result.test, "low")
                if med:
                    suggestions.append(self._format_suggestion(result.test, "considerar", med))
            elif result.status == "high":
                med = self.references.get_medications(result.test, "high")
                if med:
                    suggestions.append(self._format_suggestion(result.test, "ajustar", med))
        return suggestions

    @staticmethod
    def _format_suggestion(test: str, verb: str, med_payload) -> str:
        if isinstance(med_payload, str):
            return f"{test}: {verb} {med_payload}".strip()
        if isinstance(med_payload, list):
            names = [str(item.get("nome")) for item in med_payload if isinstance(item, dict) and item.get("nome")]
            if names:
                return f"{test}: {verb} {', '.join(names)}"
        return f"{test}: {verb} conforme protocolo"
