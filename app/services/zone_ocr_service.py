import os
from typing import Any, Dict, List, Optional
from PIL import Image

from app.services.ocr_service import run_ocr
from app.services.slip_extraction_service import extract_from_full_text, make_field
from app.services.template_service import get_template_detail, get_template_fields
from app.services.template_detection_service import detect_template_from_image
from app.services.template_ocr_service import postprocess_field
from app.services.hybrid_ocr_service import (
    _detect_qr_codes,
    _make_evidence_boxes,
    _qr_evidence_boxes,
    _normalize_rect,
)


def _rect_from_ocr_item(item):
    bbox = item.get("bbox") or []
    if not bbox:
        return None
    xs = [float(p[0]) for p in bbox]
    ys = [float(p[1]) for p in bbox]
    return [min(xs), min(ys), max(xs), max(ys)]


def _rect_center_norm(rect, image_width, image_height):
    x1, y1, x2, y2 = rect
    return ((x1 + x2) / 2 / image_width, (y1 + y2) / 2 / image_height)


def _expand_zone(field):
    margin = float(field.get("crop_margin") or 0.0)
    return [
        max(0.0, float(field["x1"]) - margin),
        max(0.0, float(field["y1"]) - margin),
        min(1.0, float(field["x2"]) + margin),
        min(1.0, float(field["y2"]) + margin),
    ]


def _center_inside_zone(rect, zone, image_width, image_height):
    cx, cy = _rect_center_norm(rect, image_width, image_height)
    return zone[0] <= cx <= zone[2] and zone[1] <= cy <= zone[3]


def _sort_ocr_items_reading_order(items):
    def key(item):
        rect = _rect_from_ocr_item(item) or [0, 0, 0, 0]
        return (round(rect[1] / 18), rect[0])
    return sorted(items, key=key)


def _avg_confidence(items):
    if not items:
        return 0.0
    return round(sum(float(item.get("confidence", 0.0)) for item in items) / len(items), 4)


def _norm_zone_to_pixel(zone, image_width, image_height):
    return [
        round(zone[0] * image_width, 2),
        round(zone[1] * image_height, 2),
        round(zone[2] * image_width, 2),
        round(zone[3] * image_height, 2),
    ]


def _zone_match_fields(template_id, ocr_items, image_width, image_height):
    fields = [f for f in get_template_fields(template_id) if f.get("is_active")]
    zone_fields = {}
    evidence_boxes = []

    for field in fields:
        field_name = field["field_name"]
        field_type = field.get("field_type") or "text"
        zone = _expand_zone(field)

        matched_items = []
        for item in ocr_items:
            rect = _rect_from_ocr_item(item)
            if not rect:
                continue
            if _center_inside_zone(rect, zone, image_width, image_height):
                matched_items.append(item)

        matched_items = _sort_ocr_items_reading_order(matched_items)
        raw_text = " ".join(str(item.get("text", "")).strip() for item in matched_items if str(item.get("text", "")).strip())
        value = postprocess_field(raw_text, field_name, field_type)
        confidence = _avg_confidence(matched_items)

        zone_fields[field_name] = {
            "value": value if value else None,
            "raw_text": raw_text if raw_text else None,
            "confidence": confidence,
            "method": "template_zone_ocr_box_matching" if value else "template_zone_no_text_found",
            "field_type": field_type,
            "display_name": field.get("display_name"),
            "template_field_id": field.get("id"),
            "zone_norm": [round(v, 6) for v in zone],
            "zone_pixel": _norm_zone_to_pixel(zone, image_width, image_height),
            "matched_ocr_items": matched_items,
        }

        # Draw the template zone itself.
        evidence_boxes.append({
            "field_name": field_name,
            "source": "template_zone",
            "method": "template_field_zone",
            "confidence": confidence,
            "bbox_pixel": _norm_zone_to_pixel(zone, image_width, image_height),
            "bbox_norm": [round(v, 6) for v in zone],
            "text": raw_text,
        })

        # Draw matched OCR item boxes too.
        for item in matched_items:
            rect = _rect_from_ocr_item(item)
            if not rect:
                continue
            evidence_boxes.append({
                "field_name": field_name,
                "source": "zone_matched_ocr",
                "method": "ocr_box_inside_template_zone",
                "confidence": item.get("confidence", 0.0),
                "bbox_pixel": [round(v, 2) for v in rect],
                "bbox_norm": [round(v, 6) for v in _normalize_rect(rect, image_width, image_height)],
                "text": item.get("text"),
            })

    return zone_fields, evidence_boxes


def _field_missing_or_low_conf(field):
    if not field:
        return True
    value = field.get("value")
    confidence = float(field.get("confidence") or 0.0)
    if value is None or value == "":
        return True
    return confidence < 0.50


def _merge_generic_and_zone(generic_extraction, zone_fields):
    generic_fields = generic_extraction.get("fields", {}) if generic_extraction else {}
    final_fields = dict(generic_fields)
    merge_report = []

    for field_name, zone_field in zone_fields.items():
        zone_value = zone_field.get("value")
        if zone_value is None or zone_value == "":
            continue

        generic_field = generic_fields.get(field_name)
        if _field_missing_or_low_conf(generic_field):
            final_fields[field_name] = make_field(
                value=zone_value,
                raw_value=zone_field.get("raw_text"),
                confidence=max(0.55, float(zone_field.get("confidence") or 0.0)),
                method="template_zone_rescue",
                warnings=["Value came from OCR text boxes inside the template field zone."],
            )
            merge_report.append({
                "field_name": field_name,
                "action": "rescued_from_template_zone",
                "generic_value": generic_field.get("value") if generic_field else None,
                "zone_value": zone_value,
            })
        else:
            # Keep generic extraction, but attach a note that zone also saw text.
            final_fields[field_name] = dict(generic_field)
            final_fields[field_name]["zone_candidate"] = {
                "value": zone_value,
                "raw_text": zone_field.get("raw_text"),
                "confidence": zone_field.get("confidence"),
            }
            merge_report.append({
                "field_name": field_name,
                "action": "generic_kept_zone_candidate_recorded",
                "generic_value": generic_field.get("value"),
                "zone_value": zone_value,
            })

    merged_extraction = dict(generic_extraction)
    merged_extraction["fields"] = final_fields
    merged_extraction["merge_report"] = merge_report

    # Recompute missing/low confidence for available field names.
    missing = []
    low = []
    for key, field in final_fields.items():
        if field.get("value") is None or field.get("value") == "":
            missing.append(key)
        elif float(field.get("confidence") or 0.0) < 0.50:
            low.append(key)
    merged_extraction["missing_fields"] = missing
    merged_extraction["low_confidence_fields"] = low

    return merged_extraction


def run_zone_ocr(image_path: str, detection_mode="auto", template_id: Optional[int] = None) -> Dict[str, Any]:
    with Image.open(image_path) as img:
        image_width, image_height = img.size

    selected_template = None
    detection = None

    if detection_mode == "manual":
        if not template_id:
            raise ValueError("template_id is required for manual mode.")
        selected_template = get_template_detail(int(template_id))
        if not selected_template:
            raise ValueError("Template not found.")
        full_ocr = run_ocr(image_path)
        ocr_items = full_ocr.get("result", {}).get("items", [])
        full_text = full_ocr.get("result", {}).get("full_text", "")
    else:
        detection = detect_template_from_image(image_path)
        full_ocr = detection.get("full_image_ocr")
        ocr_items = full_ocr.get("result", {}).get("items", [])
        full_text = full_ocr.get("result", {}).get("full_text", "")
        if detection.get("selected_template"):
            selected_template = get_template_detail(int(detection["selected_template"]["template_id"]))

    generic_extraction = extract_from_full_text(full_text, raw_items=ocr_items)
    qr_codes = _detect_qr_codes(image_path, image_width, image_height)

    evidence_boxes = []
    evidence_boxes.extend(_make_evidence_boxes(generic_extraction, ocr_items, image_width, image_height))
    evidence_boxes.extend(_qr_evidence_boxes(qr_codes))

    zone_fields = {}
    zone_evidence = []
    final_extraction = generic_extraction
    warnings = []

    if selected_template:
        zone_fields, zone_evidence = _zone_match_fields(selected_template["id"], ocr_items, image_width, image_height)
        evidence_boxes.extend(zone_evidence)
        final_extraction = _merge_generic_and_zone(generic_extraction, zone_fields)
    else:
        warnings.append("No template selected/detected. Returned generic extraction only.")
        if detection:
            warnings.append("Auto-detection confidence was not high enough. Please select a template manually.")

    if not qr_codes:
        warnings.append("No QR code detected or QR code could not be decoded.")

    return {
        "status": "success",
        "mode": "zone_ocr_v1",
        "pipeline": [
            "full_image_ocr_once",
            "generic_full_text_rules",
            "qr_extraction",
            "template_zone_ocr_box_matching",
            "merge_generic_with_zone_rescue",
        ],
        "filename": os.path.basename(image_path),
        "input_image": {
            "filename": os.path.basename(image_path),
            "width": image_width,
            "height": image_height,
        },
        "detection_mode": detection_mode,
        "detection": detection,
        "selected_template": {
            "id": selected_template["id"],
            "template_code": selected_template["template_code"],
            "template_name": selected_template["template_name"],
            "bank_name_th": selected_template["bank_name_th"],
        } if selected_template else None,
        "qr_codes": qr_codes,
        "generic_extraction": generic_extraction,
        "zone_fields": zone_fields,
        "extraction": final_extraction,
        "evidence_boxes": evidence_boxes,
        "ocr_result": full_ocr,
        "warnings": warnings,
    }
