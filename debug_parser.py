#!/usr/bin/env python3
"""Utility script to inspect PDF parsing output for lab reports."""

import argparse
from typing import List, Optional

from prescription import read_pdf, read_references, scan_results


def format_value(value):
    if isinstance(value, float) and value.is_integer():
        return f"{int(value)}"
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


def debug_pdf(pdf_path: str, gender: str, references_path: str, show_missing: bool) -> None:
    refs = read_references(references_path)
    if not refs:
        raise RuntimeError(f"Could not load references from {references_path}")

    lines = read_pdf(pdf_path)
    if not lines:
        print(f"{pdf_path}: failed to read PDF or PDF is empty")
        return

    results = scan_results(lines, refs, gender)

    print(f"\n=== {pdf_path} ({gender}) ===")

    found = [(name, data) for name, data in results.items() if data["value"] is not None]
    missing = [(name, data) for name, data in results.items() if data["value"] is None]

    if not found:
        print("No values extracted.")
    else:
        for name, data in sorted(found):
            value = format_value(data["value"])
            line = data.get("line") or ""
            print(f"- {name}: {value}\n    source: {line}")

    if show_missing and missing:
        print("\nMissing analytes (matched without numeric value):")
        for name, data in sorted(missing):
            line = data.get("line") or "(no matching line captured)"
            print(f"- {name}\n    context: {line}")


def parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Debug the lab value parser against PDFs.")
    parser.add_argument("pdf", nargs="+", help="Path(s) to PDF files inside the Web folder")
    parser.add_argument(
        "-g",
        "--gender",
        default="F",
        choices=["M", "F"],
        help="Gender flag used for ideal range selection (default: F)",
    )
    parser.add_argument(
        "-r",
        "--references",
        default="instance/references.json",
        help="Path to the references JSON file (default: instance/references.json)",
    )
    parser.add_argument(
        "--show-missing",
        action="store_true",
        help="Also list analytes that matched text but did not yield a numeric value",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)
    for pdf in args.pdf:
        debug_pdf(pdf, args.gender, args.references, args.show_missing)


if __name__ == "__main__":
    main()
