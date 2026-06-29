"""
Export all template definitions from MySQL to image + JSON files.

This is the companion tool for:

    tools/import_templates_from_folder.py

It exports templates into a folder that can be re-imported later.

Default output format:

exported_templates/
  ktb-2026-01.jpg
  ktb-2026-01.json

  kbank-2026-01.jpg
  kbank-2026-01.json

The JSON format matches the importer:
  - template_code comes from the database
  - anchors use "box": [x1, y1, x2, y2]
  - fields use "box": [x1, y1, x2, y2]
  - image filename uses template_code + original extension when possible

Run from project root:

  python tools/export_templates_to_folder.py exported_templates

Options:

  python tools/export_templates_to_folder.py exported_templates --template-code ktb-2026-01
  python tools/export_templates_to_folder.py exported_templates --active-only
  python tools/export_templates_to_folder.py exported_templates --overwrite
  python tools/export_templates_to_folder.py exported_templates --report export_report.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from werkzeug.utils import secure_filename

# Allow running from tools/ or project root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.db_service import fetch_all, fetch_one  # noqa: E402
from config import STORAGE_ROOT  # noqa: E402


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def dump_json_file(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_json_maybe(value: Any, default: Any):
    if value is None or value == "":
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def safe_template_code(template_code: str) -> str:
    safe = secure_filename(template_code or "")
    return safe or "template"


def get_templates(template_code: Optional[str] = None, active_only: bool = False) -> List[Dict[str, Any]]:
    where = []
    params = []

    if template_code:
        where.append("t.template_code = %s")
        params.append(template_code)

    if active_only:
        where.append("t.status = 'active'")

    where_sql = ""
    if where:
        where_sql = "WHERE " + " AND ".join(where)

    sql = f"""
        SELECT
            t.id,
            t.bank_id,
            t.template_code,
            t.template_name,
            t.version_label,
            t.status,
            t.expected_width,
            t.expected_height,
            t.expected_aspect_ratio,
            t.description,
            t.notes,
            t.optional_keywords_json,
            t.template_config_json,
            t.created_by,
            b.bank_code,
            b.bank_name_th,
            b.bank_name_en
        FROM templates t
        JOIN banks b ON b.id = t.bank_id
        {where_sql}
        ORDER BY t.id ASC
    """
    return fetch_all(sql, tuple(params) if params else None)


def get_template_fields(template_id: int) -> List[Dict[str, Any]]:
    sql = """
        SELECT
            id,
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
        FROM template_fields
        WHERE template_id = %s
        ORDER BY sort_order ASC, id ASC
    """
    return fetch_all(sql, (template_id,))


def get_template_anchors(template_id: int) -> List[Dict[str, Any]]:
    sql = """
        SELECT
            id,
            anchor_name,
            anchor_type,
            x1,
            y1,
            x2,
            y2,
            expected_keywords_json,
            required,
            weight
        FROM template_anchors
        WHERE template_id = %s
        ORDER BY id ASC
    """
    return fetch_all(sql, (template_id,))


def get_template_sample(template_id: int) -> Optional[Dict[str, Any]]:
    """Use the first create_sample if available, otherwise first sample."""
    sql = """
        SELECT
            id,
            sample_name,
            image_path,
            image_width,
            image_height,
            aspect_ratio,
            sample_type,
            notes
        FROM template_samples
        WHERE template_id = %s
        ORDER BY
            CASE WHEN sample_type = 'create_sample' THEN 0 ELSE 1 END,
            id ASC
        LIMIT 1
    """
    return fetch_one(sql, (template_id,))


def resolve_storage_path(relative_path: str) -> Path:
    # In DB we store paths such as "template_samples/code/file.jpg".
    # STORAGE_ROOT points to the root storage folder.
    return Path(STORAGE_ROOT) / relative_path


def choose_export_image_path(template_code: str, sample: Optional[Dict[str, Any]], output_dir: Path) -> Optional[Path]:
    if not sample or not sample.get("image_path"):
        return None

    source_path = resolve_storage_path(sample["image_path"])
    if not source_path.exists():
        return None

    ext = source_path.suffix.lower()
    if ext not in IMAGE_EXTENSIONS:
        ext = ".jpg"

    return output_dir / f"{safe_template_code(template_code)}{ext}"


def copy_sample_image(template: Dict[str, Any], sample: Optional[Dict[str, Any]], output_dir: Path, overwrite: bool) -> Optional[str]:
    target_path = choose_export_image_path(template["template_code"], sample, output_dir)
    if not target_path:
        return None

    source_path = resolve_storage_path(sample["image_path"])

    if target_path.exists() and not overwrite:
        raise FileExistsError(f"Output image already exists: {target_path}. Use --overwrite.")

    shutil.copy2(source_path, target_path)
    return target_path.name


def build_template_json(template: Dict[str, Any], fields: List[Dict[str, Any]], anchors: List[Dict[str, Any]], sample: Optional[Dict[str, Any]], image_filename: Optional[str]) -> Dict[str, Any]:
    exported_fields = []
    for field in fields:
        item = {
            "field_name": field["field_name"],
            "display_name": field["display_name"],
            "field_type": field["field_type"],
            "required": bool(field["required"]),
            "crop_margin": float(field["crop_margin"] or 0.01),
            "sort_order": int(field["sort_order"] or 0),
            "box": [
                float(field["x1"]),
                float(field["y1"]),
                float(field["x2"]),
                float(field["y2"]),
            ],
        }

        postprocess_rules = parse_json_maybe(field.get("postprocess_rules_json"), {})
        validation_rules = parse_json_maybe(field.get("validation_rules_json"), {})
        fallback_rules = parse_json_maybe(field.get("fallback_rules_json"), {})

        if postprocess_rules:
            item["postprocess_rules"] = postprocess_rules
        if validation_rules:
            item["validation_rules"] = validation_rules
        if fallback_rules:
            item["fallback_rules"] = fallback_rules
        if not field.get("is_active", True):
            item["is_active"] = False

        exported_fields.append(item)

    exported_anchors = []
    for anchor in anchors:
        exported_anchors.append({
            "anchor_name": anchor["anchor_name"],
            "anchor_type": anchor["anchor_type"],
            "expected_keywords": parse_json_maybe(anchor.get("expected_keywords_json"), []),
            "required": bool(anchor["required"]),
            "weight": float(anchor["weight"] or 1.0),
            "box": [
                float(anchor["x1"]),
                float(anchor["y1"]),
                float(anchor["x2"]),
                float(anchor["y2"]),
            ],
        })

    result = {
        "template_code": template["template_code"],
        "bank_code": template["bank_code"],
        "template_name": template["template_name"],
        "version_label": template.get("version_label"),
        "status": template.get("status", "draft"),
        "description": template.get("description"),
        "notes": template.get("notes"),
        "optional_keywords": parse_json_maybe(template.get("optional_keywords_json"), []),
        "anchors": exported_anchors,
        "fields": exported_fields,
        "template_config": parse_json_maybe(template.get("template_config_json"), {}),
        "export_meta": {
            "template_id": template["id"],
            "bank_id": template["bank_id"],
            "bank_name_th": template.get("bank_name_th"),
            "bank_name_en": template.get("bank_name_en"),
            "source_sample_id": sample.get("id") if sample else None,
            "source_sample_type": sample.get("sample_type") if sample else None,
            "image_filename": image_filename,
            "image_width": sample.get("image_width") if sample else template.get("expected_width"),
            "image_height": sample.get("image_height") if sample else template.get("expected_height"),
            "aspect_ratio": sample.get("aspect_ratio") if sample else template.get("expected_aspect_ratio"),
        }
    }

    # Remove None values at top level to keep JSON clean.
    return {k: v for k, v in result.items() if v is not None}


def export_one_template(template: Dict[str, Any], output_dir: Path, overwrite: bool) -> Dict[str, Any]:
    fields = get_template_fields(template["id"])
    anchors = get_template_anchors(template["id"])
    sample = get_template_sample(template["id"])

    image_filename = copy_sample_image(template, sample, output_dir, overwrite)
    data = build_template_json(template, fields, anchors, sample, image_filename)

    json_path = output_dir / f"{safe_template_code(template['template_code'])}.json"
    if json_path.exists() and not overwrite:
        raise FileExistsError(f"Output JSON already exists: {json_path}. Use --overwrite.")

    dump_json_file(json_path, data)

    return {
        "template_code": template["template_code"],
        "template_id": template["id"],
        "json": str(json_path),
        "image": image_filename,
        "field_count": len(fields),
        "anchor_count": len(anchors),
        "sample_id": sample.get("id") if sample else None,
        "status": "exported",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output_folder", help="Folder to export image + JSON template files into.")
    parser.add_argument("--template-code", default=None, help="Export only one template_code.")
    parser.add_argument("--active-only", action="store_true", help="Export only templates with status='active'.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing files in output folder.")
    parser.add_argument("--report", default=None, help="Optional path to save JSON export report.")
    args = parser.parse_args()

    output_dir = Path(args.output_folder).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    templates = get_templates(template_code=args.template_code, active_only=args.active_only)
    if not templates:
        raise SystemExit("No templates found.")

    results = []
    failures = []

    print(f"Found {len(templates)} template(s).")
    for template in templates:
        try:
            result = export_one_template(template, output_dir, overwrite=args.overwrite)
            results.append(result)
            print(f"OK: {result['template_code']} fields={result['field_count']} anchors={result['anchor_count']} image={result['image']}")
        except Exception as exc:
            failures.append({
                "template_code": template.get("template_code"),
                "template_id": template.get("id"),
                "error": str(exc),
            })
            print(f"ERROR: {template.get('template_code')}: {exc}")

    report = {
        "status": "success" if not failures else "partial_success",
        "output_folder": str(output_dir),
        "exported": results,
        "failures": failures,
    }

    if args.report:
        report_path = Path(args.report)
        dump_json_file(report_path, report)
        print(f"Report saved to {report_path}")

    if failures:
        raise SystemExit(1)

    print("Done.")


if __name__ == "__main__":
    main()
