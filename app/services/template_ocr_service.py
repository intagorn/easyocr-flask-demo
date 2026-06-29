import os
import re
import uuid
from PIL import Image
from app.services.ocr_service import run_ocr
from app.services.template_service import get_template_detail, get_template_fields
from config import CROP_FOLDER


def _safe_text(text):
    return (text or "").strip()


def _join_ocr_text(ocr_result):
    return _safe_text(ocr_result.get("result", {}).get("full_text", ""))


def _avg_confidence(ocr_result):
    items = ocr_result.get("result", {}).get("items", [])
    if not items:
        return 0.0
    return round(sum(float(item.get("confidence", 0.0)) for item in items) / len(items), 4)


def _normalize_spaces(text):
    return re.sub(r"\s+", " ", _safe_text(text))


def _cleanup_money(text):
    s = _normalize_spaces(text)
    s = s.replace("บาท", "").replace("บ.", "").strip()

    # OCR often reads zero as o/O in numeric areas.
    s = re.sub(r"(?<=\d)[oO](?=\d|\.|,)", "0", s)
    s = re.sub(r"(?<=\.)[oOdD]", "0", s)
    s = s.replace("O.", "0.").replace("o.", "0.")

    match = re.search(r"\d[\d,]*\.\d{2}", s)
    if match:
        return match.group(0).replace(",", "")

    match = re.search(r"\d[\d,]*", s)
    if match:
        return match.group(0).replace(",", "")

    return s


def _cleanup_reference_id(text):
    # For Thai bank transfer slips, reference_id may be numeric or alphanumeric.
    # Keep letters, digits, hyphen, slash, and underscore; remove spaces.
    s = _normalize_spaces(text)
    s = s.replace("รหัสอ้างอิง", "").replace("เลขที่รายการ", "")
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[^0-9A-Za-zก-๙\-_/.]", "", s)
    return s


def _cleanup_long_number(text):
    s = _normalize_spaces(text)
    digits = re.sub(r"\D", "", s)
    return digits or s


def _cleanup_account_mask(text):
    s = _normalize_spaces(text)
    s = s.replace(" ", "")
    s = re.sub(r"[^0-9xX\-*]", "", s)
    return s


def _cleanup_text(text):
    return _normalize_spaces(text)


def postprocess_field(raw_text, field_name, field_type):
    field_name = field_name or ""
    field_type = field_type or "text"

    if field_name == "reference_id":
        return _cleanup_reference_id(raw_text)

    if field_type == "money":
        return _cleanup_money(raw_text)
    if field_type == "long_number":
        return _cleanup_long_number(raw_text)
    if field_type == "account_mask":
        return _cleanup_account_mask(raw_text)

    return _cleanup_text(raw_text)


def _clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


def _field_crop_box(field, image_width, image_height):
    margin = float(field.get("crop_margin") or 0.0)

    x1 = float(field["x1"]) - margin
    y1 = float(field["y1"]) - margin
    x2 = float(field["x2"]) + margin
    y2 = float(field["y2"]) + margin

    x1 = _clamp(x1, 0.0, 1.0)
    y1 = _clamp(y1, 0.0, 1.0)
    x2 = _clamp(x2, 0.0, 1.0)
    y2 = _clamp(y2, 0.0, 1.0)

    left = int(round(x1 * image_width))
    top = int(round(y1 * image_height))
    right = int(round(x2 * image_width))
    bottom = int(round(y2 * image_height))

    if right <= left:
        right = min(image_width, left + 1)
    if bottom <= top:
        bottom = min(image_height, top + 1)

    return left, top, right, bottom


def run_template_ocr(template_id, image_path):
    template = get_template_detail(template_id)
    if not template:
        raise ValueError("Template not found.")

    fields = [f for f in get_template_fields(template_id) if f.get("is_active")]

    if not fields:
        raise ValueError("This template has no active fields. Please draw field boxes first.")

    run_id = uuid.uuid4().hex[:12]
    crop_dir = os.path.join(CROP_FOLDER, "template_ocr", run_id)
    os.makedirs(crop_dir, exist_ok=True)

    extracted_fields = {}
    raw_crop_ocr = {}
    warnings = []

    with Image.open(image_path) as img:
        img = img.convert("RGB")
        image_width, image_height = img.size

        for field in fields:
            field_name = field["field_name"]
            field_type = field["field_type"]

            left, top, right, bottom = _field_crop_box(field, image_width, image_height)
            crop = img.crop((left, top, right, bottom))

            crop_filename = f"{field_name}_{field['id']}.jpg"
            crop_path = os.path.join(crop_dir, crop_filename)
            crop.save(crop_path, quality=95)

            ocr_result = run_ocr(crop_path)
            raw_text = _join_ocr_text(ocr_result)
            value = postprocess_field(raw_text, field_name, field_type)
            confidence = _avg_confidence(ocr_result)

            if field.get("required") and not value:
                warnings.append(f"Required field '{field_name}' is empty.")

            extracted_fields[field_name] = {
                "value": value,
                "raw_text": raw_text,
                "confidence": confidence,
                "field_type": field_type,
                "display_name": field.get("display_name"),
                "box": {
                    "x1": float(field["x1"]),
                    "y1": float(field["y1"]),
                    "x2": float(field["x2"]),
                    "y2": float(field["y2"]),
                    "crop_margin": float(field.get("crop_margin") or 0.0),
                },
                "crop_pixel_box": [left, top, right, bottom],
                "crop_file": os.path.relpath(crop_path, CROP_FOLDER).replace("\\", "/"),
            }

            raw_crop_ocr[field_name] = ocr_result

    return {
        "status": "success",
        "mode": "template_ocr",
        "template": {
            "id": template["id"],
            "template_code": template["template_code"],
            "template_name": template["template_name"],
            "bank_name_th": template["bank_name_th"],
            "version_label": template.get("version_label"),
        },
        "input_image": {
            "filename": os.path.basename(image_path),
            "width": image_width,
            "height": image_height,
        },
        "extracted_fields": extracted_fields,
        "raw_crop_ocr": raw_crop_ocr,
        "warnings": warnings,
    }
