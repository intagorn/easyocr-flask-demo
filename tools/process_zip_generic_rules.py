#!/usr/bin/env python3
"""
Standalone ZIP batch processor for Generic Rules OCR.

Input:
    ZIP file containing slip images

Output ZIP:
    json/<same_image_stem>.json
    raw_text/<same_image_stem>.txt
    errors/<same_image_stem>.json     # only for failed images
    summary.csv
    summary.json

Run from project root:
    python tools/process_zip_generic_rules.py input_slips.zip output_results.zip

This tool uses the current generic rule OCR pipeline only. It does not use
MySQL, template manager, template zones, or any database table.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
import tempfile
import time
import traceback
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Tuple

from werkzeug.utils import secure_filename

# Allow running from project root or from tools/.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.generic_rule_ocr_service import run_generic_rule_ocr  # noqa: E402


ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
DEFAULT_MAX_IMAGES = 1000
DEFAULT_MAX_TOTAL_EXTRACTED_MB = 1024

SUMMARY_FIELDS = [
    "filename",
    "status",
    "amount",
    "fee",
    "reference_id",
    "transaction_date_raw",
    "transaction_time_raw",
    "transaction_datetime_iso_guess",
    "transfer_status",
    "source_app_or_bank",
    "sender_name",
    "sender_bank",
    "sender_account",
    "receiver_name",
    "receiver_bank",
    "receiver_account",
    "note",
    "missing_fields",
    "low_confidence_fields",
    "warnings",
    "json_file",
    "raw_text_file",
    "error_file",
]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def dump_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text or "", encoding="utf-8")


def safe_zip_member_name(member_name: str) -> Optional[str]:
    """Return safe normalized relative zip member path, or None if unsafe.

    Protects against ZIP slip paths such as ../../etc/passwd, absolute paths,
    Windows drive paths, and backslash traversal.
    """
    if not member_name:
        return None

    normalized = member_name.replace("\\", "/")
    pure = PurePosixPath(normalized)

    if pure.is_absolute():
        return None
    if any(part in ("", ".", "..") for part in pure.parts):
        return None
    if len(pure.parts) == 0:
        return None
    # Reject Windows drive-like names, e.g. C:/...
    if len(pure.parts[0]) >= 2 and pure.parts[0][1] == ":":
        return None

    return str(pure)


def is_allowed_image_name(name: str) -> bool:
    return Path(name).suffix.lower() in ALLOWED_IMAGE_EXTENSIONS


def unique_output_stem(original_name: str, used_stems: Dict[str, int]) -> str:
    """Create a safe unique output stem based on the image basename stem."""
    raw_stem = Path(original_name).stem
    safe_stem = secure_filename(raw_stem) or "image"

    count = used_stems.get(safe_stem, 0)
    used_stems[safe_stem] = count + 1
    if count == 0:
        return safe_stem
    return f"{safe_stem}_{count + 1}"


def unique_extracted_filename(original_name: str, used_names: Dict[str, int]) -> str:
    """Create a safe unique extracted image filename."""
    suffix = Path(original_name).suffix.lower()
    safe_stem = secure_filename(Path(original_name).stem) or "image"
    base_name = f"{safe_stem}{suffix}"

    count = used_names.get(base_name, 0)
    used_names[base_name] = count + 1
    if count == 0:
        return base_name
    return f"{safe_stem}_{count + 1}{suffix}"


def collect_image_members(input_zip: Path, max_images: int, max_total_extracted_mb: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return safe image members and skipped/invalid member records."""
    skipped = []
    image_infos: List[Dict[str, Any]] = []
    max_total_bytes = int(max_total_extracted_mb * 1024 * 1024)
    total_uncompressed = 0

    with zipfile.ZipFile(input_zip, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue

            safe_name = safe_zip_member_name(info.filename)
            if not safe_name:
                skipped.append({
                    "filename": info.filename,
                    "status": "skipped",
                    "reason": "unsafe_zip_path",
                })
                continue

            if not is_allowed_image_name(safe_name):
                skipped.append({
                    "filename": safe_name,
                    "status": "skipped",
                    "reason": "unsupported_extension",
                })
                continue

            total_uncompressed += int(info.file_size or 0)
            if total_uncompressed > max_total_bytes:
                skipped.append({
                    "filename": safe_name,
                    "status": "skipped",
                    "reason": f"total_uncompressed_size_exceeds_{max_total_extracted_mb}_mb",
                })
                continue

            if len(image_infos) >= max_images:
                skipped.append({
                    "filename": safe_name,
                    "status": "skipped",
                    "reason": f"max_images_exceeded_{max_images}",
                })
                continue

            image_infos.append({
                "zip_filename": info.filename,
                "safe_name": safe_name,
                "file_size": int(info.file_size or 0),
            })

    return image_infos, skipped


def extract_image_members(input_zip: Path, image_infos: Iterable[Dict[str, Any]], input_dir: Path) -> List[Dict[str, Any]]:
    """Safely extract only selected image members into input_dir."""
    input_dir.mkdir(parents=True, exist_ok=True)
    extracted = []
    used_names: Dict[str, int] = {}
    used_stems: Dict[str, int] = {}

    with zipfile.ZipFile(input_zip, "r") as zf:
        for info in image_infos:
            safe_name = info.get("safe_name")
            zip_filename = info.get("zip_filename")
            if not safe_name or not zip_filename:
                continue

            extracted_filename = unique_extracted_filename(safe_name, used_names)
            output_stem = unique_output_stem(safe_name, used_stems)
            extracted_path = input_dir / extracted_filename

            with zf.open(zip_filename, "r") as src, extracted_path.open("wb") as dst:
                shutil.copyfileobj(src, dst)

            extracted.append({
                "original_zip_path": safe_name,
                "original_filename": Path(safe_name).name,
                "extracted_filename": extracted_filename,
                "extracted_path": str(extracted_path),
                "output_stem": output_stem,
                "file_size_bytes": int(info.get("file_size") or 0),
            })

    return extracted


def field_value(result: Dict[str, Any], field_name: str) -> Any:
    fields = result.get("extraction", {}).get("fields", {})
    field = fields.get(field_name, {})
    return field.get("value")


def flatten_warnings(result: Dict[str, Any]) -> str:
    warnings = []
    warnings.extend(result.get("warnings", []) or [])
    warnings.extend(result.get("extraction", {}).get("warnings", []) or [])
    # Remove duplicates while preserving order.
    seen = set()
    deduped = []
    for warning in warnings:
        text = str(warning)
        if text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return " | ".join(deduped)


def make_summary_row_success(item: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    extraction = result.get("extraction", {})
    row = {
        "filename": item["original_filename"],
        "status": result.get("status", "success"),
        "amount": field_value(result, "amount"),
        "fee": field_value(result, "fee"),
        "reference_id": field_value(result, "reference_id"),
        "transaction_date_raw": field_value(result, "transaction_date_raw"),
        "transaction_time_raw": field_value(result, "transaction_time_raw"),
        "transaction_datetime_iso_guess": field_value(result, "transaction_datetime_iso_guess"),
        "transfer_status": field_value(result, "transfer_status"),
        "source_app_or_bank": field_value(result, "source_app_or_bank"),
        "sender_name": field_value(result, "sender_name"),
        "sender_bank": field_value(result, "sender_bank"),
        "sender_account": field_value(result, "sender_account"),
        "receiver_name": field_value(result, "receiver_name"),
        "receiver_bank": field_value(result, "receiver_bank"),
        "receiver_account": field_value(result, "receiver_account"),
        "note": field_value(result, "note"),
        "missing_fields": ";".join(extraction.get("missing_fields", []) or []),
        "low_confidence_fields": ";".join(extraction.get("low_confidence_fields", []) or []),
        "warnings": flatten_warnings(result),
        "json_file": f"json/{item['output_stem']}.json",
        "raw_text_file": f"raw_text/{item['output_stem']}.txt",
        "error_file": "",
    }
    return row


def make_summary_row_error(item: Dict[str, Any], error_json_path: str, error_message: str) -> Dict[str, Any]:
    row = {key: "" for key in SUMMARY_FIELDS}
    row.update({
        "filename": item.get("original_filename") or item.get("filename") or "",
        "status": "failed",
        "warnings": error_message,
        "error_file": error_json_path,
    })
    return row


def write_summary_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in SUMMARY_FIELDS})


def build_result_zip(output_zip: Path, output_root: Path) -> None:
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    if output_zip.exists():
        output_zip.unlink()

    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for sub in ["json", "raw_text", "errors"]:
            folder = output_root / sub
            if folder.exists():
                for path in sorted(folder.rglob("*")):
                    if path.is_file():
                        zf.write(path, path.relative_to(output_root))

        for name in ["summary.csv", "summary.json"]:
            path = output_root / name
            if path.exists():
                zf.write(path, path.name)


def process_batch(input_zip: Path, output_zip: Path, work_dir: Path, max_images: int, max_total_extracted_mb: int, progress_callback=None) -> Dict[str, Any]:
    start = time.perf_counter()
    input_zip = input_zip.resolve()
    output_zip = output_zip.resolve()
    work_dir = work_dir.resolve()

    if not input_zip.exists():
        raise FileNotFoundError(f"Input ZIP not found: {input_zip}")
    if not zipfile.is_zipfile(input_zip):
        raise ValueError(f"Input file is not a valid ZIP: {input_zip}")

    input_dir = work_dir / "input_images"
    output_root = work_dir / "output"
    json_dir = output_root / "json"
    raw_text_dir = output_root / "raw_text"
    errors_dir = output_root / "errors"
    for folder in [input_dir, json_dir, raw_text_dir, errors_dir]:
        folder.mkdir(parents=True, exist_ok=True)

    image_infos, skipped = collect_image_members(input_zip, max_images=max_images, max_total_extracted_mb=max_total_extracted_mb)
    extracted_images = extract_image_members(input_zip, image_infos, input_dir)

    if progress_callback:
        progress_callback({
            "event": "images_collected",
            "total_images": len(extracted_images),
            "skipped_files": len(skipped),
            "message": f"Found {len(extracted_images)} image(s) to process.",
        })

    summary_rows: List[Dict[str, Any]] = []
    per_file_summary: List[Dict[str, Any]] = []

    for idx, item in enumerate(extracted_images, start=1):
        image_path = Path(item["extracted_path"])
        output_stem = item["output_stem"]
        print(f"[{idx}/{len(extracted_images)}] Processing {item['original_zip_path']} ...", flush=True)

        try:
            result = run_generic_rule_ocr(str(image_path))
            result["batch"] = {
                "original_zip_path": item["original_zip_path"],
                "original_filename": item["original_filename"],
                "output_stem": output_stem,
                "processed_at": now_iso(),
            }
            # Keep original image filename visible in top-level/result sections.
            result["filename"] = item["original_filename"]
            result.setdefault("input_image", {})["filename"] = item["original_filename"]
            result["input_image"]["original_zip_path"] = item["original_zip_path"]

            json_path = json_dir / f"{output_stem}.json"
            raw_text_path = raw_text_dir / f"{output_stem}.txt"

            dump_json(json_path, result)
            raw_text = result.get("extraction", {}).get("raw_full_text") or result.get("ocr_result", {}).get("result", {}).get("full_text", "")
            write_text(raw_text_path, raw_text)

            row = make_summary_row_success(item, result)
            summary_rows.append(row)
            per_file_summary.append({
                **row,
                "original_zip_path": item["original_zip_path"],
                "output_stem": output_stem,
            })

            if progress_callback:
                progress_callback({
                    "event": "image_processed",
                    "status": "success",
                    "current_index": idx,
                    "total_images": len(extracted_images),
                    "processed_images": idx,
                    "failed_images": sum(1 for row in summary_rows if row.get("status") == "failed"),
                    "current_file": item["original_filename"],
                    "message": f"Processed {item['original_filename']}",
                })

        except Exception as exc:
            error = {
                "status": "failed",
                "filename": item["original_filename"],
                "original_zip_path": item["original_zip_path"],
                "output_stem": output_stem,
                "error_type": exc.__class__.__name__,
                "error_message": str(exc),
                "traceback": traceback.format_exc(),
                "processed_at": now_iso(),
            }
            error_path = errors_dir / f"{output_stem}.json"
            dump_json(error_path, error)
            row = make_summary_row_error(item, f"errors/{output_stem}.json", str(exc))
            summary_rows.append(row)
            per_file_summary.append({
                **row,
                "original_zip_path": item["original_zip_path"],
                "output_stem": output_stem,
            })

            if progress_callback:
                progress_callback({
                    "event": "image_processed",
                    "status": "success",
                    "current_index": idx,
                    "total_images": len(extracted_images),
                    "processed_images": idx,
                    "failed_images": sum(1 for row in summary_rows if row.get("status") == "failed"),
                    "current_file": item["original_filename"],
                    "message": f"Processed {item['original_filename']}",
                })
            print(f"  ERROR: {item['original_zip_path']}: {exc}", flush=True)

    # Add skipped files to summary.json. We do not add them to summary.csv unless they are image failures.
    elapsed = time.perf_counter() - start
    summary_json = {
        "status": "success",
        "input_zip": str(input_zip),
        "output_zip": str(output_zip),
        "created_at": now_iso(),
        "processing_seconds": round(elapsed, 4),
        "max_images": max_images,
        "max_total_extracted_mb": max_total_extracted_mb,
        "counts": {
            "image_files_found": len(extracted_images),
            "processed_success": sum(1 for row in summary_rows if row.get("status") == "success"),
            "processed_failed": sum(1 for row in summary_rows if row.get("status") == "failed"),
            "skipped_files": len(skipped),
        },
        "files": per_file_summary,
        "skipped": skipped,
        "notes": [
            "This batch uses Generic Rules OCR only. No database and no template boxes are used.",
            "Field confidence values are heuristic rule confidence, not EasyOCR character confidence.",
            "Review low-confidence and warning fields before using them for business decisions.",
        ],
    }

    write_summary_csv(output_root / "summary.csv", summary_rows)
    dump_json(output_root / "summary.json", summary_json)
    build_result_zip(output_zip, output_root)

    if progress_callback:
        progress_callback({
            "event": "batch_finished",
            "total_images": len(extracted_images),
            "processed_images": len(extracted_images),
            "failed_images": sum(1 for row in summary_rows if row.get("status") == "failed"),
            "message": "Batch processing finished.",
        })

    return summary_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Process a ZIP of slip images using Generic Rules OCR and write a result ZIP.")
    parser.add_argument("input_zip", help="Input ZIP file containing images.")
    parser.add_argument("output_zip", help="Output ZIP file to create.")
    parser.add_argument("--work-dir", default=None, help="Optional working directory. Defaults to a temporary directory.")
    parser.add_argument("--keep-work", action="store_true", help="Keep working directory after finishing.")
    parser.add_argument("--max-images", type=int, default=DEFAULT_MAX_IMAGES, help=f"Maximum images to process. Default: {DEFAULT_MAX_IMAGES}.")
    parser.add_argument("--max-total-extracted-mb", type=int, default=DEFAULT_MAX_TOTAL_EXTRACTED_MB, help=f"Maximum total uncompressed image size in MB. Default: {DEFAULT_MAX_TOTAL_EXTRACTED_MB}.")
    args = parser.parse_args()

    input_zip = Path(args.input_zip)
    output_zip = Path(args.output_zip)

    if args.work_dir:
        work_dir = Path(args.work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        cleanup = False
    else:
        work_dir = Path(tempfile.mkdtemp(prefix="generic_rules_batch_"))
        cleanup = not args.keep_work

    try:
        summary = process_batch(
            input_zip=input_zip,
            output_zip=output_zip,
            work_dir=work_dir,
            max_images=args.max_images,
            max_total_extracted_mb=args.max_total_extracted_mb,
        )
        print("Done.")
        print(f"Output ZIP: {output_zip.resolve()}")
        print(json.dumps(summary.get("counts", {}), ensure_ascii=False, indent=2))
        if args.keep_work or args.work_dir:
            print(f"Work directory: {work_dir.resolve()}")
    finally:
        if cleanup:
            shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
