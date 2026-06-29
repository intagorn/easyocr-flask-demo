import os
import uuid
from werkzeug.utils import secure_filename
from config import ALLOWED_EXTENSIONS


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS



def create_safe_filename(original_filename: str) -> str:
    safe_name = secure_filename(original_filename)
    ext = safe_name.rsplit(".", 1)[1].lower() if "." in safe_name else "jpg"
    unique_id = uuid.uuid4().hex[:12]
    return f"{unique_id}.{ext}"



def save_upload_file(file, upload_folder: str) -> str:
    filename = create_safe_filename(file.filename)
    filepath = os.path.join(upload_folder, filename)
    file.save(filepath)
    return filepath



def save_template_sample_file(file, sample_root_folder: str, template_code: str):
    safe_template_code = secure_filename(template_code) or "template"
    subfolder = os.path.join(sample_root_folder, safe_template_code)
    os.makedirs(subfolder, exist_ok=True)

    filename = create_safe_filename(file.filename)
    filepath = os.path.join(subfolder, filename)
    file.save(filepath)

    relative_path = os.path.join("template_samples", safe_template_code, filename)
    return filepath, relative_path.replace("\\", "/")
