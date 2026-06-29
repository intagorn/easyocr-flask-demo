import os
from flask import Flask
from config import (
    UPLOAD_FOLDER,
    RESULT_FOLDER,
    TEMPLATE_SAMPLE_FOLDER,
    BATCH_FOLDER,
    JOBS_FOLDER,
    CROP_FOLDER,
    MAX_CONTENT_LENGTH,
)


def create_app():
    app = Flask(__name__)

    app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
    app.config["RESULT_FOLDER"] = RESULT_FOLDER
    app.config["TEMPLATE_SAMPLE_FOLDER"] = TEMPLATE_SAMPLE_FOLDER
    app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
    app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "easyocr-template-dev-secret")

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(RESULT_FOLDER, exist_ok=True)
    os.makedirs(TEMPLATE_SAMPLE_FOLDER, exist_ok=True)
    os.makedirs(BATCH_FOLDER, exist_ok=True)
    os.makedirs(JOBS_FOLDER, exist_ok=True)
    os.makedirs(CROP_FOLDER, exist_ok=True)

    from app.routes.web_routes import web_bp
    from app.routes.api_routes import api_bp

    app.register_blueprint(web_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    # Start the file-based batch job worker. This MVP is designed for one
    # Gunicorn worker process. If you increase Gunicorn workers later, move this
    # to an external worker process or Redis/Celery/RQ.
    try:
        from app.services.batch_job_service import start_background_worker
        if os.environ.get("EASYOCR_DISABLE_JOB_WORKER", "0") != "1":
            start_background_worker()
    except Exception as exc:
        print(f"Warning: could not start batch job worker: {exc}")

    return app
