import os
import time
from datetime import datetime
import easyocr
from config import OCR_LANGUAGES, USE_GPU

_readers = {}


def get_reader(languages=None):
    """
    Load EasyOCR reader once and reuse it.
    Loading the model every request would be very slow.
    """
    language_list = list(languages or OCR_LANGUAGES)
    reader_key = tuple(language_list)

    if reader_key not in _readers:
        _readers[reader_key] = easyocr.Reader(language_list, gpu=USE_GPU)

    return _readers[reader_key]


def convert_bbox(bbox):
    """
    Convert EasyOCR bbox values to normal Python floats
    so Flask can serialize them as JSON.
    """
    return [[float(point[0]), float(point[1])] for point in bbox]


def run_ocr(image_path: str) -> dict:
    """
    Run OCR on one image and return a JSON-ready dictionary.
    """
    reader = get_reader()

    start_time = time.perf_counter()
    raw_results = reader.readtext(image_path)
    ocr_seconds = time.perf_counter() - start_time

    items = []
    full_text_lines = []

    for bbox, text, confidence in raw_results:
        item = {
            "text": str(text),
            "confidence": round(float(confidence), 4),
            "bbox": convert_bbox(bbox),
        }
        items.append(item)
        full_text_lines.append(str(text))

    result = {
        "status": "success",
        "filename": os.path.basename(image_path),
        "engine": {
            "name": "EasyOCR",
            "languages": OCR_LANGUAGES,
            "gpu": USE_GPU,
        },
        "processing_time": {
            "ocr_seconds": round(float(ocr_seconds), 4),
        },
        "result": {
            "full_text": "\n".join(full_text_lines),
            "num_regions": int(len(items)),
            "items": items,
        },
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "warnings": [],
    }

    return result
