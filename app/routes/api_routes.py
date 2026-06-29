import os
import json
from flask import Blueprint, request, jsonify, current_app, send_file
from PIL import Image
from app.utils.file_utils import allowed_file, save_upload_file, save_template_sample_file
from app.services.ocr_service import run_ocr
from app.services.slip_extraction_service import extract_from_full_text
from app.services.template_ocr_service import run_template_ocr
from app.services.template_detection_service import detect_template_from_image
from app.services.hybrid_ocr_service import run_hybrid_ocr
from app.services.zone_ocr_service import run_zone_ocr
from app.services.generic_rule_ocr_service import run_generic_rule_ocr
from app.services.batch_job_service import (
    create_batch_job,
    get_job_status,
    list_jobs,
    result_file_path,
    reset_active_jobs,
    MAX_ACTIVE_JOBS,
)
from config import ALLOWED_EXTENSIONS, SAVE_RESULTS
from app.services.template_service import (
    get_banks,
    get_templates,
    get_template_by_code,
    create_template,
    create_template_sample,
    create_template_field,
    create_template_anchor,
    update_template_field_box,
    update_template_anchor_box,
)

api_bp = Blueprint("api", __name__)


@api_bp.route("/health", methods=["GET"])
def health_check():
    return jsonify({
        "status": "ok",
        "message": "EasyOCR Flask API is running.",
        "features": [
            "single_image_ocr",
            "demo_bank_slip_rule_extraction",
            "mysql_template_list",
            "template_create_draft",
            "hybrid_ocr_qr_generic_extraction",
            "zone_ocr_template_zone_matching",
            "generic_rules_ocr_no_db",
            "batch_generic_rules_file_jobs",
        ],
    })


@api_bp.route("/banks", methods=["GET"])
def api_banks():
    try:
        return jsonify({
            "status": "success",
            "banks": get_banks(),
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
        }), 500


@api_bp.route("/templates", methods=["GET"])
def api_templates():
    try:
        return jsonify({
            "status": "success",
            "templates": get_templates(),
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
        }), 500


@api_bp.route("/templates", methods=["POST"])
def api_create_template():
    try:
        bank_id = request.form.get("bank_id", "").strip()
        template_code = request.form.get("template_code", "").strip()
        template_name = request.form.get("template_name", "").strip()
        version_label = request.form.get("version_label", "").strip()
        created_by = request.form.get("created_by", "").strip()
        notes = request.form.get("notes", "").strip()
        file = request.files.get("sample_image")

        if not bank_id:
            return jsonify({"status": "error", "message": "bank_id is required."}), 400
        if not template_code:
            return jsonify({"status": "error", "message": "template_code is required."}), 400
        if not template_name:
            return jsonify({"status": "error", "message": "template_name is required."}), 400
        if file is None or file.filename == "":
            return jsonify({"status": "error", "message": "sample_image is required."}), 400
        if not allowed_file(file.filename):
            return jsonify({"status": "error", "message": "Unsupported image type."}), 400
        if get_template_by_code(template_code):
            return jsonify({"status": "error", "message": "Template code already exists."}), 400

        template_id = create_template(
            bank_id=int(bank_id),
            template_code=template_code,
            template_name=template_name,
            version_label=version_label,
            created_by=created_by or None,
        )

        saved_path, relative_path = save_template_sample_file(
            file,
            current_app.config["TEMPLATE_SAMPLE_FOLDER"],
            template_code,
        )

        width = None
        height = None
        aspect_ratio = None
        try:
            with Image.open(saved_path) as img:
                width, height = img.size
                if height:
                    aspect_ratio = round(width / height, 6)
        except Exception:
            pass

        sample_id = create_template_sample(
            template_id=template_id,
            sample_name=file.filename,
            image_path=relative_path,
            image_width=width,
            image_height=height,
            aspect_ratio=aspect_ratio,
            uploaded_by=created_by or None,
            notes=notes or None,
        )

        return jsonify({
            "status": "success",
            "template_id": template_id,
            "sample_id": sample_id,
            "template_code": template_code,
            "message": "Template created successfully as draft.",
            "sample_image_path": relative_path,
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


def _parse_normalized_box(payload):
    required_keys = ["x1", "y1", "x2", "y2"]
    values = []
    for key in required_keys:
        if key not in payload:
            raise ValueError(f"{key} is required.")
        values.append(float(payload[key]))

    x1, y1, x2, y2 = values

    # Normalize order in case the user dragged from right-to-left or bottom-to-top.
    x_min = max(0.0, min(x1, x2))
    y_min = max(0.0, min(y1, y2))
    x_max = min(1.0, max(x1, x2))
    y_max = min(1.0, max(y1, y2))

    if x_max - x_min < 0.001 or y_max - y_min < 0.001:
        raise ValueError("Box is too small. Please draw a larger rectangle.")

    return x_min, y_min, x_max, y_max



@api_bp.route("/templates/<int:template_id>/fields/<int:field_id>/box", methods=["PATCH"])
def api_update_template_field_box(template_id, field_id):
    try:
        data = request.get_json(force=True)
        required = ["x1", "y1", "x2", "y2"]
        for key in required:
            if key not in data:
                return jsonify({
                    "status": "error",
                    "message": f"Missing required value: {key}",
                }), 400

        x1 = float(data["x1"])
        y1 = float(data["y1"])
        x2 = float(data["x2"])
        y2 = float(data["y2"])

        if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
            return jsonify({
                "status": "error",
                "message": "Invalid box. Values must satisfy 0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1.",
            }), 400

        affected = update_template_field_box(template_id, field_id, x1, y1, x2, y2)

        # PyMySQL/MySQL may return 0 for UPDATE when values are considered unchanged
        # after FLOAT rounding, even though the row exists. Do not treat that as a hard error.
        return jsonify({
            "status": "success",
            "field_id": field_id,
            "affected_rows": affected,
            "box": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
        }), 500


@api_bp.route("/templates/<int:template_id>/anchors/<int:anchor_id>/box", methods=["PATCH"])
def api_update_template_anchor_box(template_id, anchor_id):
    try:
        data = request.get_json(force=True)
        required = ["x1", "y1", "x2", "y2"]
        for key in required:
            if key not in data:
                return jsonify({
                    "status": "error",
                    "message": f"Missing required value: {key}",
                }), 400

        x1 = float(data["x1"])
        y1 = float(data["y1"])
        x2 = float(data["x2"])
        y2 = float(data["y2"])

        if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
            return jsonify({
                "status": "error",
                "message": "Invalid box. Values must satisfy 0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1.",
            }), 400

        affected = update_template_anchor_box(template_id, anchor_id, x1, y1, x2, y2)

        # PyMySQL/MySQL may return 0 for UPDATE when values are considered unchanged
        # after FLOAT rounding, even though the row exists. Do not treat that as a hard error.
        return jsonify({
            "status": "success",
            "anchor_id": anchor_id,
            "affected_rows": affected,
            "box": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
        }), 500


@api_bp.route("/templates/<int:template_id>/fields", methods=["POST"])
def api_create_template_field(template_id):
    try:
        payload = request.get_json(silent=True) or {}
        x1, y1, x2, y2 = _parse_normalized_box(payload)

        field_name = (payload.get("field_name") or "").strip()
        display_name = (payload.get("display_name") or "").strip()
        field_type = (payload.get("field_type") or "text").strip()
        required = bool(payload.get("required", False))
        crop_margin = float(payload.get("crop_margin", 0.01))
        sort_order = int(payload.get("sort_order", 0))

        if not field_name:
            return jsonify({"status": "error", "message": "field_name is required."}), 400
        if not display_name:
            display_name = field_name

        field_id = create_template_field(
            template_id=template_id,
            field_name=field_name,
            display_name=display_name,
            field_type=field_type,
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2,
            required=required,
            crop_margin=crop_margin,
            sort_order=sort_order,
        )

        return jsonify({
            "status": "success",
            "message": "Template field saved.",
            "field_id": field_id,
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@api_bp.route("/templates/<int:template_id>/anchors", methods=["POST"])
def api_create_template_anchor(template_id):
    try:
        payload = request.get_json(silent=True) or {}
        x1, y1, x2, y2 = _parse_normalized_box(payload)

        anchor_name = (payload.get("anchor_name") or "").strip()
        anchor_type = (payload.get("anchor_type") or "key_area").strip()
        keywords_text = (payload.get("expected_keywords") or "").strip()
        required = bool(payload.get("required", False))
        weight = float(payload.get("weight", 1.0))

        if not anchor_name:
            return jsonify({"status": "error", "message": "anchor_name is required."}), 400

        expected_keywords_json = None
        if keywords_text:
            keywords = [kw.strip() for kw in keywords_text.split(",") if kw.strip()]
            expected_keywords_json = json.dumps(keywords, ensure_ascii=False)

        anchor_id = create_template_anchor(
            template_id=template_id,
            anchor_name=anchor_name,
            anchor_type=anchor_type,
            x1=x1,
            y1=y1,
            x2=x2,
            y2=y2,
            expected_keywords_json=expected_keywords_json,
            required=required,
            weight=weight,
        )

        return jsonify({
            "status": "success",
            "message": "Template anchor saved.",
            "anchor_id": anchor_id,
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@api_bp.route("/zone-ocr", methods=["POST"])
def api_zone_ocr():
    if "image" not in request.files:
        return jsonify({
            "status": "error",
            "message": "No image file found. Please upload with form field name 'image'.",
        }), 400

    file = request.files["image"]

    if file.filename == "":
        return jsonify({
            "status": "error",
            "message": "No selected file.",
        }), 400

    if not allowed_file(file.filename):
        return jsonify({
            "status": "error",
            "message": "Unsupported file type.",
            "details": {
                "allowed_extensions": sorted(list(ALLOWED_EXTENSIONS)),
            },
        }), 400

    detection_mode = request.form.get("detection_mode", "auto").strip() or "auto"
    template_id_text = request.form.get("template_id", "").strip()
    template_id = int(template_id_text) if template_id_text else None

    try:
        filepath = save_upload_file(file, current_app.config["UPLOAD_FOLDER"])
        result = run_zone_ocr(filepath, detection_mode=detection_mode, template_id=template_id)
        return jsonify(result)

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
        }), 500





@api_bp.route("/batch-jobs/reset-active", methods=["POST"])
def api_reset_active_batch_jobs():
    result = reset_active_jobs("Manually reset from API.")
    return jsonify(result)


@api_bp.route("/batch-jobs", methods=["POST"])
def api_create_batch_job():
    """Create a queued ZIP batch job.

    Form field:
        zip_file: ZIP file containing images
    """
    file = request.files.get("zip_file") or request.files.get("file") or request.files.get("zip")
    if file is None or file.filename == "":
        return jsonify({
            "status": "error",
            "message": "No ZIP file found. Upload using form field 'zip_file'.",
        }), 400

    result = create_batch_job(
        file=file,
        submitted_by=request.form.get("submitted_by") or request.headers.get("X-Submitted-By"),
    )

    if result.get("status") == "error":
        code = 429 if "Queue is full" in result.get("message", "") else 400
        return jsonify(result), code

    job_id = result["job_id"]
    return jsonify({
        "status": "queued",
        "job": result,
        "job_id": job_id,
        "status_url": f"/api/batch-jobs/{job_id}",
        "download_url": f"/api/batch-jobs/{job_id}/download",
        "summary_json_url": f"/api/batch-jobs/{job_id}/summary.json",
        "max_active_jobs": MAX_ACTIVE_JOBS,
    }), 202


@api_bp.route("/batch-jobs", methods=["GET"])
def api_list_batch_jobs():
    limit = request.args.get("limit", "100")
    try:
        limit_int = max(1, min(500, int(limit)))
    except ValueError:
        limit_int = 100

    return jsonify({
        "status": "success",
        "jobs": list_jobs(limit=limit_int),
        "max_active_jobs": MAX_ACTIVE_JOBS,
    })


@api_bp.route("/batch-jobs/<job_id>", methods=["GET"])
def api_get_batch_job(job_id):
    job = get_job_status(job_id)
    if not job:
        return jsonify({
            "status": "error",
            "message": "Job not found.",
            "job_id": job_id,
        }), 404

    if job.get("status") == "finished":
        job = {
            **job,
            "download_url": f"/api/batch-jobs/{job_id}/download",
            "summary_json_url": f"/api/batch-jobs/{job_id}/summary.json",
        }

    return jsonify({
        "status": "success",
        "job": job,
    })


@api_bp.route("/batch-jobs/<job_id>/summary.json", methods=["GET"])
def api_batch_job_summary_json(job_id):
    job = get_job_status(job_id)
    if not job:
        return jsonify({
            "status": "error",
            "message": "Job not found.",
        }), 404

    path = result_file_path(job_id, "summary.json")
    if not path.exists():
        return jsonify({
            "status": "error",
            "message": "summary.json is not available yet.",
            "job_status": job.get("status"),
        }), 404

    return send_file(path, mimetype="application/json", as_attachment=False, download_name="summary.json")


@api_bp.route("/batch-jobs/<job_id>/download", methods=["GET"])
def api_batch_job_download(job_id):
    job = get_job_status(job_id)
    if not job:
        return jsonify({
            "status": "error",
            "message": "Job not found.",
        }), 404

    path = result_file_path(job_id, "result.zip")
    if not path.exists():
        return jsonify({
            "status": "error",
            "message": "result.zip is not available yet.",
            "job_status": job.get("status"),
        }), 404

    return send_file(path, mimetype="application/zip", as_attachment=True, download_name=f"{job_id}_result.zip")


@api_bp.route("/generic-rules-ocr", methods=["POST"])
def api_generic_rules_ocr():
    if "image" not in request.files:
        return jsonify({
            "status": "error",
            "message": "No image file found. Please upload with form field name 'image'.",
        }), 400

    file = request.files["image"]

    if file.filename == "":
        return jsonify({
            "status": "error",
            "message": "No selected file.",
        }), 400

    if not allowed_file(file.filename):
        return jsonify({
            "status": "error",
            "message": "Unsupported file type.",
            "details": {
                "allowed_extensions": sorted(list(ALLOWED_EXTENSIONS)),
            },
        }), 400

    try:
        filepath = save_upload_file(file, current_app.config["UPLOAD_FOLDER"])
        result = run_generic_rule_ocr(filepath)
        return jsonify(result)

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
        }), 500


@api_bp.route("/hybrid-ocr", methods=["POST"])
def api_hybrid_ocr():
    if "image" not in request.files:
        return jsonify({
            "status": "error",
            "message": "No image file found. Please upload with form field name 'image'.",
        }), 400

    file = request.files["image"]

    if file.filename == "":
        return jsonify({
            "status": "error",
            "message": "No selected file.",
        }), 400

    if not allowed_file(file.filename):
        return jsonify({
            "status": "error",
            "message": "Unsupported file type.",
            "details": {
                "allowed_extensions": sorted(list(ALLOWED_EXTENSIONS)),
            },
        }), 400

    try:
        filepath = save_upload_file(file, current_app.config["UPLOAD_FOLDER"])
        result = run_hybrid_ocr(filepath)
        return jsonify(result)

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
        }), 500


@api_bp.route("/template-ocr", methods=["POST"])
def api_template_ocr():
    if "image" not in request.files:
        return jsonify({
            "status": "error",
            "message": "No image file found. Please upload with form field name 'image'.",
        }), 400

    detection_mode = request.form.get("detection_mode", "manual").strip().lower()
    template_id = request.form.get("template_id", "").strip()
    file = request.files["image"]

    if file.filename == "":
        return jsonify({
            "status": "error",
            "message": "No selected file.",
        }), 400

    if not allowed_file(file.filename):
        return jsonify({
            "status": "error",
            "message": "Unsupported file type.",
            "details": {
                "allowed_extensions": sorted(list(ALLOWED_EXTENSIONS)),
            },
        }), 400

    try:
        filepath = save_upload_file(file, current_app.config["UPLOAD_FOLDER"])

        if detection_mode == "auto":
            detection = detect_template_from_image(filepath)
            selected = detection.get("selected_template")

            if not selected:
                return jsonify({
                    "status": "needs_template_selection",
                    "message": "Could not confidently detect the template. Please select one manually.",
                    "template_detection": detection,
                })

            result = run_template_ocr(int(selected["template_id"]), filepath)
            result["template_detection"] = detection
            result["detection_mode"] = "auto"
            return jsonify(result)

        # Manual mode fallback.
        if not template_id:
            return jsonify({
                "status": "error",
                "message": "template_id is required in manual mode.",
            }), 400

        result = run_template_ocr(int(template_id), filepath)
        result["detection_mode"] = "manual"
        return jsonify(result)

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
        }), 500


@api_bp.route("/ocr", methods=["POST"])
def ocr_single_image():
    if "image" not in request.files:
        return jsonify({
            "status": "error",
            "message": "No image file found. Please upload with form field name 'image'.",
        }), 400

    file = request.files["image"]

    if file.filename == "":
        return jsonify({
            "status": "error",
            "message": "No selected file.",
        }), 400

    if not allowed_file(file.filename):
        return jsonify({
            "status": "error",
            "message": "Unsupported file type.",
            "details": {
                "allowed_extensions": sorted(list(ALLOWED_EXTENSIONS)),
            },
        }), 400

    try:
        filepath = save_upload_file(file, current_app.config["UPLOAD_FOLDER"])

        result = run_ocr(filepath)

        full_text = result.get("result", {}).get("full_text", "")
        raw_items = result.get("result", {}).get("items", [])
        extraction = extract_from_full_text(full_text, raw_items=raw_items)
        result["extraction"] = extraction

        if SAVE_RESULTS:
            result_filename = os.path.splitext(os.path.basename(filepath))[0] + ".json"
            result_path = os.path.join(current_app.config["RESULT_FOLDER"], result_filename)

            with open(result_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            result["saved_result_file"] = result_filename

        return jsonify(result)

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
        }), 500
