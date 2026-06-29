import os
from PIL import Image
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    current_app,
    flash,
    abort,
    send_file,
    jsonify,
)
from app.services.template_service import (
    get_banks_with_template_counts,
    get_templates,
    get_banks,
    get_template_by_code,
    get_template_detail,
    get_template_samples,
    get_template_fields,
    get_template_anchors,
    get_template_sample_by_id,
    create_template,
    create_template_sample,
)
from app.utils.file_utils import allowed_file, save_template_sample_file
from app.services.batch_job_service import (
    create_batch_job,
    list_jobs,
    get_job_status,
    result_file_path,
    get_job_result_rows,
    get_per_image_json_path,
    find_input_image_path,
    reset_active_jobs,
    MAX_ACTIVE_JOBS,
)

web_bp = Blueprint("web", __name__)


@web_bp.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@web_bp.route("/ocr", methods=["GET"])
def ocr_page():
    return render_template("ocr.html")




@web_bp.route("/hybrid-ocr", methods=["GET"])
def hybrid_ocr_page():
    return render_template("hybrid_ocr.html")



@web_bp.route("/generic-rules-ocr", methods=["GET"])
def generic_rules_ocr_page():
    return render_template("generic_rules_ocr.html")




@web_bp.route("/batch-generic-rules-ocr", methods=["GET", "POST"])
def batch_generic_rules_ocr_page():
    form_error = None

    if request.method == "POST":
        file = request.files.get("zip_file")
        if file is None or file.filename == "":
            form_error = "Please select a ZIP file."
        else:
            result = create_batch_job(file=file, submitted_by=request.form.get("submitted_by") or None)
            if result.get("status") == "error":
                form_error = result.get("message", "Could not create job.")
            else:
                return redirect(url_for("web.job_detail_page", job_id=result["job_id"]))

    return render_template(
        "batch_generic_rules_ocr.html",
        form_error=form_error,
        max_active_jobs=MAX_ACTIVE_JOBS,
    )



@web_bp.route("/jobs/reset-active", methods=["POST"])
def jobs_reset_active_page():
    reset_active_jobs("Manually reset from Jobs page.")
    return redirect(url_for("web.jobs_page"))


@web_bp.route("/jobs", methods=["GET"])
def jobs_page():
    jobs = list_jobs(limit=100)
    return render_template(
        "jobs.html",
        jobs=jobs,
        max_active_jobs=MAX_ACTIVE_JOBS,
    )


@web_bp.route("/jobs/<job_id>", methods=["GET"])
def job_detail_page(job_id):
    job = get_job_status(job_id)
    if not job:
        abort(404)

    total = int(job.get("total_images") or 0)
    done = int(job.get("processed_images") or 0)
    progress_percent = 0
    if total > 0:
        progress_percent = min(100, round(done * 100 / total))

    return render_template(
        "job_detail.html",
        job=job,
        progress_percent=progress_percent,
    )


@web_bp.route("/jobs/<job_id>/results", methods=["GET"])
def job_results_page(job_id):
    job = get_job_status(job_id)
    if not job:
        abort(404)

    rows = get_job_result_rows(job_id)

    return render_template(
        "job_results.html",
        job=job,
        rows=rows,
    )


@web_bp.route("/jobs/<job_id>/download", methods=["GET"])
def job_download(job_id):
    job = get_job_status(job_id)
    if not job:
        abort(404)

    path = result_file_path(job_id, "result.zip")
    if not path.exists():
        abort(404)

    return send_file(path, mimetype="application/zip", as_attachment=True, download_name=f"{job_id}_result.zip")


@web_bp.route("/jobs/<job_id>/summary.json", methods=["GET"])
def job_summary_json(job_id):
    job = get_job_status(job_id)
    if not job:
        abort(404)

    path = result_file_path(job_id, "summary.json")
    if not path.exists():
        abort(404)

    return send_file(path, mimetype="application/json", as_attachment=False, download_name="summary.json")


@web_bp.route("/jobs/<job_id>/json/<output_stem>.json", methods=["GET"])
def job_image_json(job_id, output_stem):
    job = get_job_status(job_id)
    if not job:
        abort(404)

    path = get_per_image_json_path(job_id, output_stem)
    if not path.exists():
        abort(404)

    return send_file(path, mimetype="application/json", as_attachment=False, download_name=f"{output_stem}.json")


@web_bp.route("/jobs/<job_id>/images/<output_stem>", methods=["GET"])
def job_image_preview(job_id, output_stem):
    job = get_job_status(job_id)
    if not job:
        abort(404)

    filename = request.args.get("filename")
    path = find_input_image_path(job_id, output_stem, filename=filename)
    if not path:
        abort(404)

    return send_file(path)


@web_bp.route("/jobs/<job_id>/status.json", methods=["GET"])
def job_status_json(job_id):
    job = get_job_status(job_id)
    if not job:
        abort(404)
    return jsonify({
        "status": "success",
        "job": job,
    })


@web_bp.route("/zone-ocr", methods=["GET"])
def zone_ocr_page():
    templates = []
    db_error = None

    try:
        templates = get_templates()
    except Exception as exc:
        db_error = str(exc)

    return render_template(
        "zone_ocr.html",
        templates=templates,
        db_error=db_error,
    )


@web_bp.route("/template-ocr", methods=["GET"])
def template_ocr_page():
    templates = []
    db_error = None

    try:
        templates = get_templates()
    except Exception as exc:
        db_error = str(exc)

    return render_template(
        "template_ocr.html",
        templates=templates,
        db_error=db_error,
    )


@web_bp.route("/templates", methods=["GET"])
def templates_page():
    banks = []
    templates = []
    db_error = None

    try:
        banks = get_banks_with_template_counts()
        templates = get_templates()
    except Exception as exc:
        db_error = str(exc)

    return render_template(
        "templates.html",
        banks=banks,
        templates=templates,
        db_error=db_error,
    )


@web_bp.route("/templates/new", methods=["GET", "POST"])
def template_create_page():
    db_error = None
    form_error = None
    banks = []

    try:
        banks = get_banks()
    except Exception as exc:
        db_error = str(exc)

    if request.method == "POST":
        if db_error:
            return render_template("template_new.html", banks=banks, db_error=db_error, form_error=None)

        bank_id = request.form.get("bank_id", "").strip()
        template_code = request.form.get("template_code", "").strip()
        template_name = request.form.get("template_name", "").strip()
        version_label = request.form.get("version_label", "").strip()
        created_by = request.form.get("created_by", "").strip()
        notes = request.form.get("notes", "").strip()
        file = request.files.get("sample_image")

        if not bank_id:
            form_error = "Please select a bank."
        elif not template_code:
            form_error = "Please enter template code."
        elif not template_name:
            form_error = "Please enter template name."
        elif file is None or file.filename == "":
            form_error = "Please upload one sample slip image."
        elif not allowed_file(file.filename):
            form_error = "Unsupported image type. Allowed: png, jpg, jpeg, bmp, webp."
        elif get_template_by_code(template_code):
            form_error = "Template code already exists. Please use a different template code."

        if form_error:
            return render_template(
                "template_new.html",
                banks=banks,
                db_error=db_error,
                form_error=form_error,
            )

        try:
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

            create_template_sample(
                template_id=template_id,
                sample_name=file.filename,
                image_path=relative_path,
                image_width=width,
                image_height=height,
                aspect_ratio=aspect_ratio,
                uploaded_by=created_by or None,
                notes=notes or None,
            )

            flash(f"Template '{template_name}' created successfully as draft.", "success")
            return redirect(url_for("web.template_detail_page", template_id=template_id))

        except Exception as exc:
            form_error = str(exc)

    return render_template(
        "template_new.html",
        banks=banks,
        db_error=db_error,
        form_error=form_error,
    )


@web_bp.route("/templates/<int:template_id>", methods=["GET"])
def template_detail_page(template_id):
    template = None
    samples = []
    fields = []
    anchors = []
    db_error = None

    try:
        template = get_template_detail(template_id)
        if not template:
            abort(404)

        samples = get_template_samples(template_id)
        fields = get_template_fields(template_id)
        anchors = get_template_anchors(template_id)
    except Exception as exc:
        db_error = str(exc)

    return render_template(
        "template_detail.html",
        template=template,
        samples=samples,
        fields=fields,
        anchors=anchors,
        db_error=db_error,
    )


@web_bp.route("/template-samples/<int:sample_id>/image", methods=["GET"])
def template_sample_image(sample_id):
    sample = get_template_sample_by_id(sample_id)
    if not sample:
        abort(404)

    # Security: use DB sample id, then join only the relative path stored in DB.
    # Reject absolute paths and parent traversal.
    relative_path = sample.get("image_path") or ""
    normalized = relative_path.replace("\\", "/").lstrip("/")

    if ".." in normalized.split("/"):
        abort(400)

    # image_path includes "template_samples/..." but TEMPLATE_SAMPLE_FOLDER already points there.
    prefix = "template_samples/"
    if normalized.startswith(prefix):
        normalized_inside_template_root = normalized[len(prefix):]
    else:
        normalized_inside_template_root = normalized

    full_path = os.path.abspath(
        os.path.join(current_app.config["TEMPLATE_SAMPLE_FOLDER"], normalized_inside_template_root)
    )
    storage_root = os.path.abspath(current_app.config["TEMPLATE_SAMPLE_FOLDER"])

    if not full_path.startswith(storage_root):
        abort(400)

    if not os.path.exists(full_path):
        abort(404)

    return send_file(full_path)
