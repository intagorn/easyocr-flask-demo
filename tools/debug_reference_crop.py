import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np
from PIL import Image

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.services.generic_rule_ocr_service import (
    best_reference_candidate_from_english_ocr,
    extract_generic_rules_from_full_text,
    reference_crop_rects,
)
from app.services.ocr_service import get_reader, run_ocr


def easyocr_result_to_json(raw_results):
    items = []
    for bbox, text, confidence in raw_results:
        items.append({
            "bbox": [[float(point[0]), float(point[1])] for point in bbox],
            "text": str(text),
            "confidence": round(float(confidence), 4),
        })
    return items


def main():
    parser = argparse.ArgumentParser(description="Debug reference-id crop and English-only OCR.")
    parser.add_argument("image_path")
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()

    image_path = args.image_path
    if args.output_dir:
        output_dir = args.output_dir
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = os.path.join("storage", "debug_reference_crop", stamp)

    os.makedirs(output_dir, exist_ok=True)

    safe_input_path = os.path.join(output_dir, "input_copy.jpg")
    with Image.open(image_path) as img:
        img = img.convert("RGB")
        image_width, image_height = img.size
        img.save(safe_input_path)

    # Use the ASCII-safe copy path for EasyOCR/OpenCV on Windows.
    ocr_result = run_ocr(safe_input_path)
    full_text = ocr_result.get("result", {}).get("full_text", "")
    ocr_items = ocr_result.get("result", {}).get("items", [])
    extraction = extract_generic_rules_from_full_text(full_text, ocr_items)
    reference_field = extraction.get("fields", {}).get("reference_id", {})
    crop_rects = reference_crop_rects(ocr_items, reference_field, image_width, image_height)

    debug = {
        "image_path": image_path,
        "safe_input_path": safe_input_path,
        "image_size": {"width": image_width, "height": image_height},
        "reference_field_before_rescue": reference_field,
        "crop_rects": crop_rects,
        "full_text": full_text,
        "crops": [],
    }

    with open(os.path.join(output_dir, "first_pass_ocr.json"), "w", encoding="utf-8") as f:
        json.dump(ocr_result, f, ensure_ascii=False, indent=2)

    with open(os.path.join(output_dir, "first_pass_extraction.json"), "w", encoding="utf-8") as f:
        json.dump(extraction, f, ensure_ascii=False, indent=2)

    default_reader = get_reader()
    crop_records = []
    with Image.open(safe_input_path) as img:
        for idx, rect in enumerate(crop_rects, start=1):
            crop_path = os.path.join(output_dir, f"reference_crop_{idx}.jpg")
            crop = img.crop(tuple(rect)).convert("RGB")
            crop.save(crop_path)
            default_raw_results = default_reader.readtext(np.array(crop))
            crop_record = {
                "index": idx,
                "rect": rect,
                "crop_path": crop_path,
                "default_ocr_items": easyocr_result_to_json(default_raw_results),
            }
            crop_records.append(crop_record)
            debug["crops"].append(crop_record)

            with open(os.path.join(output_dir, f"reference_crop_{idx}_default_ocr.json"), "w", encoding="utf-8") as f:
                json.dump(crop_record, f, ensure_ascii=False, indent=2)

    try:
        en_reader = get_reader(["en"])
        for crop_record in crop_records:
            with Image.open(crop_record["crop_path"]) as crop:
                raw_results = en_reader.readtext(np.array(crop.convert("RGB")))
                english_ocr_items = easyocr_result_to_json(raw_results)
                best_candidate = best_reference_candidate_from_english_ocr(raw_results)

                crop_record["english_ocr_items"] = english_ocr_items
                crop_record["best_candidate"] = best_candidate

                with open(os.path.join(output_dir, f"reference_crop_{crop_record['index']}_english_ocr.json"), "w", encoding="utf-8") as f:
                    json.dump(crop_record, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        debug["english_ocr_error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }

    with open(os.path.join(output_dir, "debug_summary.json"), "w", encoding="utf-8") as f:
        json.dump(debug, f, ensure_ascii=False, indent=2)

    print(json.dumps({
        "output_dir": os.path.abspath(output_dir),
        "reference_value": reference_field.get("value"),
        "crop_count": len(crop_rects),
        "english_ocr_error": debug.get("english_ocr_error"),
        "crop_paths": [crop.get("crop_path") for crop in debug.get("crops", [])],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
