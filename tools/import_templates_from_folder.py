"""
Import template definitions from a folder into MySQL and storage.

Expected folder format:

template/
  ktb-2026-01.jpg
  ktb-2026-01.json

  kbank-2026-01.jpg
  kbank-2026-01.json

The image file stem is the template key/identifier by default.
For example:
  ktb-2026-01.jpg  -> template_code = ktb-2026-01

Run from project root:

  python tools/import_templates_from_folder.py template

Optional:

  python tools/import_templates_from_folder.py template --dry-run
  python tools/import_templates_from_folder.py template --replace-existing
  python tools/import_templates_from_folder.py template --created-by admin

The script:
  - reads image + same-name JSON
  - creates/updates the template record
  - copies image to storage/template_samples/<template_code>/
  - inserts template_samples with sample_type='create_sample'
  - inserts template_fields
  - inserts template_anchors

JSON format supports two styles:

1) Minimal style, filename as key:

{
  "bank_code": "KTB",
  "template_name": "Krungthai transfer slip",
  "fields": [
    {
      "field_name": "reference_id",
      "display_name": "รหัสอ้างอิง",
      "field_type": "text",
      "required": true,
      "box": [0.30, 0.23, 0.82, 0.28]
    }
  ],
  "anchors": [
    {
      "anchor_name": "success_text",
      "anchor_type": "text",
      "expected_keywords": ["โอนเงินสำเร็จ"],
      "required": true,
      "box": [0.15, 0.15, 0.60, 0.23]
    }
  ]
}

2) Explicit style:

{
  "template_code": "ktb-2026-01",
  "bank_code": "KTB",
  "template_name": "Krungthai transfer slip",
  "version_label": "v1",
  "status": "draft",
  "description": "...",
  "notes": "...",
  "optional_keywords": ["Krungthai", "กรุงไทย"],
  "fields": [...],
  "anchors": [...]
}

Box values are normalized coordinates:
  [x1, y1, x2, y2]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image
from werkzeug.utils import secure_filename

# Allow running from tools/ or project root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.db_service import fetch_one, fetch_all, execute_insert, execute_sql  # noqa: E402
from config import TEMPLATE_SAMPLE_FOLDER  # noqa: E402


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

VALID_FIELD_NAMES = {
    "reference_id",
    "amount",
    "fee",
    "transaction_datetime",
    "transaction_date_raw",
    "transaction_time_raw",
    "sender_name",
    "sender_bank",
    "sender_account",
    "receiver_name",
    "receiver_bank",
    "receiver_account",
    "transfer_status",
    "note",
    "source_app_or_bank",
}

VALID_FIELD_TYPES = {
    "text",
    "thai_name",
    "bank_name",
    "money",
    "account_mask",
    "long_number",
    "datetime",
    "date",
    "time",
    "status",
}


VALID_ANCHOR_TYPES = {
    "key_area",
    "logo_area",
    "text_label",
    "success_text",
    "other",
}

ANCHOR_TYPE_ALIASES = {
    "text": "text_label",
    "label": "text_label",
    "logo": "logo_area",
    "logo_or_text": "logo_area",
    "bank_logo": "logo_area",
    "qr": "key_area",
    "qr_code": "key_area",
    "key": "key_area",
}


def normalize_anchor_type(anchor: Dict[str, Any]) -> str:
    """Map friendly JSON anchor types to the DB ENUM values.

    DB ENUM:
        key_area, logo_area, text_label, success_text, other
    """
    raw = str(anchor.get("anchor_type", "") or "").strip().lower()
    anchor_name = str(anchor.get("anchor_name", "") or "").strip().lower()

    if raw in VALID_ANCHOR_TYPES:
        return raw

    if raw in ANCHOR_TYPE_ALIASES:
        return ANCHOR_TYPE_ALIASES[raw]

    # Useful automatic mapping by anchor_name.
    if "success" in anchor_name or "สำเร็จ" in anchor_name:
        return "success_text"
    if "logo" in anchor_name or "bank_logo" in anchor_name:
        return "logo_area"
    if "label" in anchor_name or anchor_name.endswith("_label"):
        return "text_label"
    if "qr" in anchor_name:
        return "key_area"

    return "other"


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def validate_box(box: Any, context: str) -> Tuple[float, float, float, float]:
    if not isinstance(box, list) or len(box) != 4:
        raise ValueError(f"{context}: box must be [x1, y1, x2, y2].")

    try:
        x1, y1, x2, y2 = [float(v) for v in box]
    except Exception as exc:
        raise ValueError(f"{context}: box values must be numeric.") from exc

    if not (0 <= x1 <= 1 and 0 <= y1 <= 1 and 0 <= x2 <= 1 and 0 <= y2 <= 1):
        raise ValueError(f"{context}: box values must be between 0 and 1.")

    if x2 <= x1 or y2 <= y1:
        raise ValueError(f"{context}: box must satisfy x2 > x1 and y2 > y1.")

    return x1, y1, x2, y2


def get_bank_id(template_data: Dict[str, Any]) -> int:
    bank_id = template_data.get("bank_id")
    bank_code = template_data.get("bank_code")
    bank_name = template_data.get("bank_name")

    if bank_id:
        row = fetch_one("SELECT id FROM banks WHERE id = %s", (bank_id,))
        if row:
            return int(row["id"])
        raise ValueError(f"bank_id not found: {bank_id}")

    if bank_code:
        row = fetch_one(
            """
            SELECT id FROM banks
            WHERE LOWER(bank_code) = LOWER(%s)
               OR LOWER(bank_name_en) LIKE LOWER(%s)
               OR LOWER(bank_name_th) LIKE LOWER(%s)
            LIMIT 1
            """,
            (bank_code, f"%{bank_code}%", f"%{bank_code}%"),
        )
        if row:
            return int(row["id"])
        raise ValueError(f"bank_code not found in banks table: {bank_code}")

    if bank_name:
        row = fetch_one(
            """
            SELECT id FROM banks
            WHERE bank_name_th LIKE %s OR bank_name_en LIKE %s
            LIMIT 1
            """,
            (f"%{bank_name}%", f"%{bank_name}%"),
        )
        if row:
            return int(row["id"])
        raise ValueError(f"bank_name not found in banks table: {bank_name}")

    raise ValueError("Template JSON must contain bank_code, bank_id, or bank_name.")


def find_existing_template(template_code: str) -> Optional[Dict[str, Any]]:
    return fetch_one(
        "SELECT id, template_code FROM templates WHERE template_code = %s LIMIT 1",
        (template_code,),
    )


def delete_existing_template_children(template_id: int) -> None:
    execute_sql("DELETE FROM template_anchors WHERE template_id = %s", (template_id,))
    execute_sql("DELETE FROM template_fields WHERE template_id = %s", (template_id,))
    execute_sql("DELETE FROM template_samples WHERE template_id = %s", (template_id,))


def update_existing_template(template_id: int, data: Dict[str, Any], bank_id: int, expected_width: int, expected_height: int, aspect_ratio: float, created_by: Optional[str]) -> None:
    sql = """
        UPDATE templates
        SET
            bank_id = %s,
            template_name = %s,
            version_label = %s,
            status = %s,
            expected_width = %s,
            expected_height = %s,
            expected_aspect_ratio = %s,
            description = %s,
            notes = %s,
            optional_keywords_json = %s,
            template_config_json = %s,
            created_by = COALESCE(created_by, %s)
        WHERE id = %s
    """
    execute_sql(sql, (
        bank_id,
        data.get("template_name"),
        data.get("version_label"),
        data.get("status", "draft"),
        expected_width,
        expected_height,
        aspect_ratio,
        data.get("description"),
        data.get("notes"),
        dump_json(data.get("optional_keywords", [])),
        dump_json(data.get("template_config", {})),
        created_by,
        template_id,
    ))


def insert_template(template_code: str, data: Dict[str, Any], bank_id: int, expected_width: int, expected_height: int, aspect_ratio: float, created_by: Optional[str]) -> int:
    sql = """
        INSERT INTO templates (
            bank_id,
            template_code,
            template_name,
            version_label,
            status,
            expected_width,
            expected_height,
            expected_aspect_ratio,
            description,
            notes,
            optional_keywords_json,
            template_config_json,
            created_by
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    return execute_insert(sql, (
        bank_id,
        template_code,
        data.get("template_name") or template_code,
        data.get("version_label"),
        data.get("status", "draft"),
        expected_width,
        expected_height,
        aspect_ratio,
        data.get("description"),
        data.get("notes"),
        dump_json(data.get("optional_keywords", [])),
        dump_json(data.get("template_config", {})),
        created_by,
    ))


def copy_image_to_storage(image_path: Path, template_code: str) -> Tuple[Path, str]:
    safe_template_code = secure_filename(template_code) or "template"
    target_dir = Path(TEMPLATE_SAMPLE_FOLDER) / safe_template_code
    target_dir.mkdir(parents=True, exist_ok=True)

    safe_name = secure_filename(image_path.name) or image_path.name
    target_path = target_dir / safe_name

    # Avoid overwriting by adding suffix.
    if target_path.exists():
        stem = target_path.stem
        suffix = target_path.suffix
        i = 2
        while True:
            candidate = target_dir / f"{stem}_{i}{suffix}"
            if not candidate.exists():
                target_path = candidate
                break
            i += 1

    shutil.copy2(image_path, target_path)

    relative_path = Path("template_samples") / safe_template_code / target_path.name
    return target_path, str(relative_path).replace("\\", "/")


def insert_template_sample(template_id: int, image_path: Path, relative_path: str, width: int, height: int, aspect_ratio: float, uploaded_by: Optional[str]) -> int:
    sql = """
        INSERT INTO template_samples (
            template_id,
            sample_name,
            image_path,
            image_width,
            image_height,
            aspect_ratio,
            sample_type,
            uploaded_by,
            notes
        )
        VALUES (%s, %s, %s, %s, %s, %s, 'create_sample', %s, %s)
    """
    return execute_insert(sql, (
        template_id,
        image_path.name,
        relative_path,
        width,
        height,
        aspect_ratio,
        uploaded_by,
        "Imported by tools/import_templates_from_folder.py",
    ))


def insert_fields(template_id: int, fields: List[Dict[str, Any]]) -> int:
    count = 0
    for idx, field in enumerate(fields):
        field_name = field.get("field_name")
        if not field_name:
            raise ValueError(f"fields[{idx}]: field_name is required.")
        if field_name not in VALID_FIELD_NAMES:
            print(f"WARNING: fields[{idx}] has non-standard field_name: {field_name}")

        field_type = field.get("field_type", "text")
        if field_type not in VALID_FIELD_TYPES:
            print(f"WARNING: fields[{idx}] has non-standard field_type: {field_type}")

        x1, y1, x2, y2 = validate_box(field.get("box"), f"fields[{idx}] {field_name}")

        sql = """
            INSERT INTO template_fields (
                template_id,
                field_name,
                display_name,
                field_type,
                x1,
                y1,
                x2,
                y2,
                required,
                crop_margin,
                sort_order,
                postprocess_rules_json,
                validation_rules_json,
                fallback_rules_json,
                is_active
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
        """
        execute_insert(sql, (
            template_id,
            field_name,
            field.get("display_name") or field_name,
            field_type,
            x1,
            y1,
            x2,
            y2,
            bool(field.get("required", False)),
            float(field.get("crop_margin", 0.01)),
            int(field.get("sort_order", idx + 1)),
            dump_json(field.get("postprocess_rules", field.get("postprocess_rule", {}))),
            dump_json(field.get("validation_rules", {})),
            dump_json(field.get("fallback_rules", {})),
        ))
        count += 1
    return count


def insert_anchors(template_id: int, anchors: List[Dict[str, Any]]) -> int:
    count = 0
    for idx, anchor in enumerate(anchors):
        anchor_name = anchor.get("anchor_name")
        if not anchor_name:
            raise ValueError(f"anchors[{idx}]: anchor_name is required.")

        x1, y1, x2, y2 = validate_box(anchor.get("box"), f"anchors[{idx}] {anchor_name}")

        expected_keywords = anchor.get("expected_keywords", anchor.get("expected_keywords_json", []))
        if isinstance(expected_keywords, str):
            try:
                expected_keywords = json.loads(expected_keywords)
            except Exception:
                expected_keywords = [expected_keywords]

        sql = """
            INSERT INTO template_anchors (
                template_id,
                anchor_name,
                anchor_type,
                x1,
                y1,
                x2,
                y2,
                expected_keywords_json,
                required,
                weight
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        execute_insert(sql, (
            template_id,
            anchor_name,
            normalize_anchor_type(anchor),
            x1,
            y1,
            x2,
            y2,
            dump_json(expected_keywords or []),
            bool(anchor.get("required", False)),
            float(anchor.get("weight", 1.0)),
        ))
        count += 1
    return count


def import_one_pair(image_path: Path, json_path: Path, args) -> Dict[str, Any]:
    data = load_json(json_path)

    template_code = data.get("template_code") or image_path.stem
    template_code = str(template_code).strip()
    if not template_code:
        raise ValueError(f"{json_path}: template_code could not be determined.")

    with Image.open(image_path) as img:
        width, height = img.size
    aspect_ratio = round(width / height, 6) if height else None

    bank_id = get_bank_id(data)

    if args.dry_run:
        fields = data.get("fields", [])
        anchors = data.get("anchors", [])
        for i, field in enumerate(fields):
            validate_box(field.get("box"), f"fields[{i}] {field.get('field_name')}")
        for i, anchor in enumerate(anchors):
            validate_box(anchor.get("box"), f"anchors[{i}] {anchor.get('anchor_name')}")
        return {
            "template_code": template_code,
            "bank_id": bank_id,
            "image": str(image_path),
            "json": str(json_path),
            "width": width,
            "height": height,
            "aspect_ratio": aspect_ratio,
            "fields": len(fields),
            "anchors": len(anchors),
            "dry_run": True,
        }

    existing = find_existing_template(template_code)
    if existing and not args.replace_existing:
        raise ValueError(
            f"Template already exists: {template_code}. "
            "Use --replace-existing to replace fields/anchors/samples."
        )

    if existing and args.replace_existing:
        template_id = int(existing["id"])
        delete_existing_template_children(template_id)
        update_existing_template(
            template_id,
            data,
            bank_id,
            width,
            height,
            aspect_ratio,
            args.created_by,
        )
        action = "updated"
    else:
        template_id = insert_template(
            template_code,
            data,
            bank_id,
            width,
            height,
            aspect_ratio,
            args.created_by,
        )
        action = "inserted"

    copied_path, relative_path = copy_image_to_storage(image_path, template_code)
    sample_id = insert_template_sample(
        template_id,
        image_path,
        relative_path,
        width,
        height,
        aspect_ratio,
        args.created_by,
    )

    field_count = insert_fields(template_id, data.get("fields", []))
    anchor_count = insert_anchors(template_id, data.get("anchors", []))

    return {
        "template_code": template_code,
        "template_id": template_id,
        "sample_id": sample_id,
        "action": action,
        "bank_id": bank_id,
        "image": str(image_path),
        "json": str(json_path),
        "stored_image_path": relative_path,
        "width": width,
        "height": height,
        "aspect_ratio": aspect_ratio,
        "fields": field_count,
        "anchors": anchor_count,
    }


def find_pairs(folder: Path) -> List[Tuple[Path, Path]]:
    pairs = []
    for image_path in sorted(folder.iterdir()):
        if not image_path.is_file():
            continue
        if image_path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue

        json_path = image_path.with_suffix(".json")
        if not json_path.exists():
            print(f"SKIP: missing JSON for {image_path.name}: expected {json_path.name}")
            continue

        pairs.append((image_path, json_path))

    return pairs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", help="Folder containing same-name image + JSON template files.")
    parser.add_argument("--dry-run", action="store_true", help="Validate files but do not insert/copy.")
    parser.add_argument("--replace-existing", action="store_true", help="Replace fields/anchors/samples for existing template_code.")
    parser.add_argument("--created-by", default=None, help="Name/user stored in created_by/uploaded_by.")
    parser.add_argument("--report", default=None, help="Optional path to save JSON import report.")
    args = parser.parse_args()

    folder = Path(args.folder).resolve()
    if not folder.exists() or not folder.is_dir():
        raise SystemExit(f"Folder not found: {folder}")

    pairs = find_pairs(folder)
    if not pairs:
        raise SystemExit(f"No image+json pairs found in {folder}")

    results = []
    failures = []

    print(f"Found {len(pairs)} template pair(s).")
    for image_path, json_path in pairs:
        try:
            result = import_one_pair(image_path, json_path, args)
            results.append(result)
            print(f"OK: {result['template_code']} ({result.get('action', 'dry-run')}) fields={result['fields']} anchors={result['anchors']}")
        except Exception as exc:
            failures.append({
                "image": str(image_path),
                "json": str(json_path),
                "error": str(exc),
            })
            print(f"ERROR: {image_path.name}: {exc}")

    report = {
        "status": "success" if not failures else "partial_success",
        "dry_run": bool(args.dry_run),
        "folder": str(folder),
        "imported": results,
        "failures": failures,
    }

    if args.report:
        report_path = Path(args.report)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Report saved to {report_path}")

    if failures:
        raise SystemExit(1)

    print("Done.")


if __name__ == "__main__":
    main()
