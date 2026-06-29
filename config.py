import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# For local Windows development, this defaults to project/storage.
# For server deployment, set EASYOCR_STORAGE_ROOT=/var/easyocr_demo_storage.
STORAGE_ROOT = os.environ.get("EASYOCR_STORAGE_ROOT", os.path.join(BASE_DIR, "storage"))

UPLOAD_FOLDER = os.path.join(STORAGE_ROOT, "uploads")
RESULT_FOLDER = os.path.join(STORAGE_ROOT, "results")
TEMPLATE_SAMPLE_FOLDER = os.path.join(STORAGE_ROOT, "template_samples")
BATCH_FOLDER = os.path.join(STORAGE_ROOT, "batches")
JOBS_FOLDER = os.path.join(STORAGE_ROOT, "jobs")
CROP_FOLDER = os.path.join(STORAGE_ROOT, "crops")

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "bmp", "webp"}

MAX_CONTENT_LENGTH = int(os.environ.get("EASYOCR_MAX_CONTENT_MB", "300")) * 1024 * 1024  # default 300 MB for batch ZIP upload

OCR_LANGUAGES = ["th", "en"]
USE_GPU = False

SAVE_UPLOADS = True
SAVE_RESULTS = True
