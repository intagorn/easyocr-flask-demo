import json
import re
from PIL import Image
from app.services.ocr_service import run_ocr
from app.services.db_service import fetch_all


def _safe_str(value):
    return str(value or "").strip()


def _normalize_for_match(text):
    text = _safe_str(text).lower()
    text = re.sub(r"\s+", "", text)
    return text


def _parse_json_list(value):
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        return []
    return []


def _keyword_matches(full_text_norm, keyword):
    kw = _normalize_for_match(keyword)
    if not kw:
        return False
    return kw in full_text_norm


def get_detection_templates():
    """Return templates and basic metadata for detection.

    For MVP, any template except deprecated can be detected. In production, use active only.
    """
    sql = """
        SELECT
            t.id,
            t.template_code,
            t.template_name,
            t.version_label,
            t.status,
            t.optional_keywords_json,
            COALESCE(t.expected_aspect_ratio, AVG(ts.aspect_ratio)) AS expected_aspect_ratio,
            b.id AS bank_id,
            b.bank_code,
            b.bank_name_th,
            b.bank_name_en,
            COUNT(DISTINCT tf.id) AS field_count
        FROM templates t
        JOIN banks b ON b.id = t.bank_id
        LEFT JOIN template_samples ts ON ts.template_id = t.id
        LEFT JOIN template_fields tf ON tf.template_id = t.id AND tf.is_active = TRUE
        WHERE t.status <> 'deprecated'
        GROUP BY
            t.id,
            t.template_code,
            t.template_name,
            t.version_label,
            t.status,
            t.optional_keywords_json,
            t.expected_aspect_ratio,
            b.id,
            b.bank_code,
            b.bank_name_th,
            b.bank_name_en
        ORDER BY t.updated_at DESC, t.id DESC
    """
    return fetch_all(sql)


def get_all_bank_keywords():
    sql = """
        SELECT bank_id, keyword, keyword_type, weight
        FROM bank_keywords
        ORDER BY weight DESC, id ASC
    """
    rows = fetch_all(sql)
    result = {}
    for row in rows:
        result.setdefault(row["bank_id"], []).append(row)
    return result


def get_all_template_anchors():
    sql = """
        SELECT
            id,
            template_id,
            anchor_name,
            anchor_type,
            expected_keywords_json,
            required,
            weight
        FROM template_anchors
        ORDER BY weight DESC, id ASC
    """
    rows = fetch_all(sql)
    result = {}
    for row in rows:
        result.setdefault(row["template_id"], []).append(row)
    return result


def _score_aspect_ratio(expected_aspect_ratio, image_aspect_ratio):
    if not expected_aspect_ratio or not image_aspect_ratio:
        return 0, None
    try:
        expected = float(expected_aspect_ratio)
        actual = float(image_aspect_ratio)
    except Exception:
        return 0, None
    if expected <= 0 or actual <= 0:
        return 0, None

    diff = abs(expected - actual)
    if diff <= 0.02:
        return 12, f"aspect ratio very close ({actual:.4f} vs {expected:.4f})"
    if diff <= 0.06:
        return 7, f"aspect ratio close ({actual:.4f} vs {expected:.4f})"
    if diff <= 0.12:
        return 3, f"aspect ratio somewhat close ({actual:.4f} vs {expected:.4f})"
    return -6, f"aspect ratio differs ({actual:.4f} vs {expected:.4f})"


def detect_template_from_image(image_path, max_candidates=5, high_threshold=35, min_margin=8):
    """Run full-image OCR and score all templates.

    Returns detection payload. If selected_template is None, caller should ask user to select manually.
    """
    full_ocr = run_ocr(image_path)
    full_text = full_ocr.get("result", {}).get("full_text", "")
    full_text_norm = _normalize_for_match(full_text)

    with Image.open(image_path) as img:
        width, height = img.size
        image_aspect_ratio = round(width / height, 6) if height else None

    templates = get_detection_templates()
    bank_keywords = get_all_bank_keywords()
    anchors_by_template = get_all_template_anchors()

    candidates = []

    for template in templates:
        score = 0.0
        reasons = []
        matched_keywords = []

        # Basic bank names can act as keywords even if bank_keywords table is incomplete.
        basic_keywords = [
            template.get("bank_code"),
            template.get("bank_name_th"),
            template.get("bank_name_en"),
        ]
        for kw in basic_keywords:
            if _keyword_matches(full_text_norm, kw):
                score += 10
                matched_keywords.append(_safe_str(kw))
                reasons.append(f"matched bank name/code: {kw}")
                break

        # Bank keyword table.
        for row in bank_keywords.get(template["bank_id"], []):
            kw = row.get("keyword")
            if _keyword_matches(full_text_norm, kw):
                weight = float(row.get("weight") or 1.0)
                add = min(18, 8 * weight)
                score += add
                matched_keywords.append(_safe_str(kw))
                reasons.append(f"matched bank keyword: {kw}")

        # Optional template keywords.
        for kw in _parse_json_list(template.get("optional_keywords_json")):
            if _keyword_matches(full_text_norm, kw):
                score += 10
                matched_keywords.append(_safe_str(kw))
                reasons.append(f"matched template keyword: {kw}")

        # Anchors expected keywords.
        anchors = anchors_by_template.get(template["id"], [])
        required_anchor_misses = []
        for anchor in anchors:
            anchor_keywords = _parse_json_list(anchor.get("expected_keywords_json"))
            anchor_matched = False
            for kw in anchor_keywords:
                if _keyword_matches(full_text_norm, kw):
                    weight = float(anchor.get("weight") or 1.0)
                    add = min(25, 12 * weight)
                    score += add
                    matched_keywords.append(_safe_str(kw))
                    reasons.append(f"matched anchor {anchor.get('anchor_name')}: {kw}")
                    anchor_matched = True
                    break
            if anchor.get("required") and anchor_keywords and not anchor_matched:
                required_anchor_misses.append(anchor.get("anchor_name"))

        if required_anchor_misses:
            penalty = 8 * len(required_anchor_misses)
            score -= penalty
            reasons.append(f"required anchor keyword not found: {', '.join(required_anchor_misses)}")

        aspect_score, aspect_reason = _score_aspect_ratio(
            template.get("expected_aspect_ratio"), image_aspect_ratio
        )
        score += aspect_score
        if aspect_reason:
            reasons.append(aspect_reason)

        field_count = int(template.get("field_count") or 0)
        if field_count > 0:
            score += min(8, field_count)
            reasons.append(f"template has {field_count} active fields")
        else:
            score -= 20
            reasons.append("template has no active fields")

        candidates.append({
            "template_id": template["id"],
            "template_code": template["template_code"],
            "template_name": template["template_name"],
            "bank_name_th": template["bank_name_th"],
            "bank_code": template["bank_code"],
            "version_label": template.get("version_label"),
            "status": template.get("status"),
            "field_count": field_count,
            "expected_aspect_ratio": float(template["expected_aspect_ratio"]) if template.get("expected_aspect_ratio") else None,
            "score": round(score, 2),
            "matched_keywords": sorted(list(set(matched_keywords))),
            "reasons": reasons,
        })

    candidates.sort(key=lambda item: item["score"], reverse=True)
    top_candidates = candidates[:max_candidates]

    selected = None
    confidence = "low"
    if top_candidates:
        best = top_candidates[0]
        second_score = top_candidates[1]["score"] if len(top_candidates) > 1 else 0
        margin = best["score"] - second_score
        if best["score"] >= high_threshold and (margin >= min_margin or len(top_candidates) == 1):
            selected = best
            confidence = "high"
        elif best["score"] >= 25:
            confidence = "medium"

    return {
        "status": "success",
        "input_image": {
            "width": width,
            "height": height,
            "aspect_ratio": image_aspect_ratio,
        },
        "full_image_ocr": full_ocr,
        "selected_template": selected,
        "confidence": confidence,
        "thresholds": {
            "high_threshold": high_threshold,
            "min_margin": min_margin,
        },
        "candidates": top_candidates,
    }
