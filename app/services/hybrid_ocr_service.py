import os
import re
from typing import Any, Dict, List, Optional
import cv2
from PIL import Image

from app.services.ocr_service import run_ocr
from app.services.slip_extraction_service import extract_from_full_text


def _rect_from_bbox_points(bbox_points):
    xs = [float(p[0]) for p in bbox_points]
    ys = [float(p[1]) for p in bbox_points]
    return [min(xs), min(ys), max(xs), max(ys)]


def _normalize_rect(rect, width, height):
    x1, y1, x2, y2 = rect
    return [
        max(0.0, min(1.0, x1 / width)),
        max(0.0, min(1.0, y1 / height)),
        max(0.0, min(1.0, x2 / width)),
        max(0.0, min(1.0, y2 / height)),
    ]


def _merge_rects(rects):
    if not rects:
        return None
    return [
        min(r[0] for r in rects),
        min(r[1] for r in rects),
        max(r[2] for r in rects),
        max(r[3] for r in rects),
    ]


def _compact(s):
    return re.sub(r"\s+", "", str(s or "").lower())


def _clean_for_match(s):
    s = str(s or "").lower()
    s = s.replace(":", "")
    s = re.sub(r"\s+", "", s)
    return s


def _find_matching_ocr_boxes(raw_value, value, items):
    if raw_value is None and value is None:
        return []

    candidates = []
    raw_clean = _clean_for_match(raw_value)
    value_clean = _clean_for_match(value)

    for item in items:
        text = item.get("text", "")
        text_clean = _clean_for_match(text)

        matched = False
        if raw_clean and (raw_clean in text_clean or text_clean in raw_clean):
            matched = True
        elif value_clean and (value_clean in text_clean or text_clean in value_clean):
            matched = True

        # For money, ignore comma differences.
        if not matched and value_clean:
            text_money = text_clean.replace(",", "")
            value_money = value_clean.replace(",", "")
            if value_money and (value_money in text_money or text_money in value_money):
                matched = True

        if matched:
            candidates.append(item)

    return candidates


def _make_evidence_boxes(extraction, ocr_items, image_width, image_height):
    evidence = []
    fields = extraction.get("fields", {}) if extraction else {}

    for field_name, field in fields.items():
        value = field.get("value")
        raw_value = field.get("raw_value")
        boxes = _find_matching_ocr_boxes(raw_value, value, ocr_items)
        rects = [_rect_from_bbox_points(item["bbox"]) for item in boxes if item.get("bbox")]

        merged = _merge_rects(rects)
        if not merged:
            continue

        evidence.append({
            "field_name": field_name,
            "source": "full_ocr",
            "method": field.get("method"),
            "confidence": field.get("confidence", 0.0),
            "bbox_pixel": [round(v, 2) for v in merged],
            "bbox_norm": [round(v, 6) for v in _normalize_rect(merged, image_width, image_height)],
            "text": raw_value if raw_value is not None else value,
        })

    return evidence


def _extract_qr_reference_candidates(qr_text: str) -> List[str]:
    """Return conservative long alphanumeric substrings from QR payload.

    This is intentionally not used as final truth yet. It is for debugging and later comparison.
    """
    if not qr_text:
        return []

    # Keep long chunks that contain both letters/digits or are long numeric chunks.
    chunks = re.findall(r"[A-Za-z0-9]{12,}", qr_text)
    candidates = []
    for chunk in chunks:
        if chunk not in candidates:
            candidates.append(chunk)
    return candidates[:5]


def _detect_qr_codes(image_path: str, image_width: int, image_height: int) -> List[Dict[str, Any]]:
    img = cv2.imread(image_path)
    if img is None:
        return []

    detector = cv2.QRCodeDetector()
    qr_results = []

    # Try multi-detection first.
    try:
        ok, decoded_info, points, _ = detector.detectAndDecodeMulti(img)
        if ok and points is not None:
            for idx, text in enumerate(decoded_info):
                if not text:
                    continue
                pts = points[idx].tolist()
                rect = _rect_from_bbox_points(pts)
                qr_results.append({
                    "data": text,
                    "reference_candidates": _extract_qr_reference_candidates(text),
                    "bbox_points": pts,
                    "bbox_pixel": [round(v, 2) for v in rect],
                    "bbox_norm": [round(v, 6) for v in _normalize_rect(rect, image_width, image_height)],
                    "method": "opencv_detectAndDecodeMulti",
                })
    except Exception:
        pass

    if qr_results:
        return qr_results

    # Fallback single QR detection.
    try:
        text, points, _ = detector.detectAndDecode(img)
        if text and points is not None:
            pts = points[0].tolist() if len(points.shape) == 3 else points.tolist()
            rect = _rect_from_bbox_points(pts)
            qr_results.append({
                "data": text,
                "reference_candidates": _extract_qr_reference_candidates(text),
                "bbox_points": pts,
                "bbox_pixel": [round(v, 2) for v in rect],
                "bbox_norm": [round(v, 6) for v in _normalize_rect(rect, image_width, image_height)],
                "method": "opencv_detectAndDecode",
            })
    except Exception:
        pass

    return qr_results


def _qr_evidence_boxes(qr_codes):
    evidence = []
    for qr in qr_codes:
        evidence.append({
            "field_name": "qr_code",
            "source": "qr_detector",
            "method": qr.get("method"),
            "confidence": 1.0,
            "bbox_pixel": qr.get("bbox_pixel"),
            "bbox_norm": qr.get("bbox_norm"),
            "text": qr.get("data"),
        })
    return evidence


def run_hybrid_ocr(image_path: str) -> Dict[str, Any]:
    with Image.open(image_path) as img:
        image_width, image_height = img.size

    ocr_result = run_ocr(image_path)
    full_text = ocr_result.get("result", {}).get("full_text", "")
    ocr_items = ocr_result.get("result", {}).get("items", [])

    generic_extraction = extract_from_full_text(full_text, raw_items=ocr_items)
    qr_codes = _detect_qr_codes(image_path, image_width, image_height)

    evidence_boxes = []
    evidence_boxes.extend(_make_evidence_boxes(generic_extraction, ocr_items, image_width, image_height))
    evidence_boxes.extend(_qr_evidence_boxes(qr_codes))

    warnings = []
    if not qr_codes:
        warnings.append("No QR code detected or QR code could not be decoded.")

    return {
        "status": "success",
        "mode": "hybrid_ocr_v1",
        "pipeline": [
            "full_image_ocr_once",
            "qr_extraction",
            "generic_full_text_bank_transfer_rules",
            "visual_evidence_boxes",
        ],
        "filename": os.path.basename(image_path),
        "input_image": {
            "filename": os.path.basename(image_path),
            "width": image_width,
            "height": image_height,
        },
        "qr_codes": qr_codes,
        "extraction": generic_extraction,
        "evidence_boxes": evidence_boxes,
        "ocr_result": ocr_result,
        "warnings": warnings,
    }
