import os
import re
from typing import Any, Dict, List, Optional, Tuple
from PIL import Image

from app.services.ocr_service import run_ocr
from app.services.hybrid_ocr_service import _detect_qr_codes, _normalize_rect


BANK_KEYWORDS = {
    "krungthai": {
        "display_name": "Krungthai Bank / ธนาคารกรุงไทย",
        "keywords": ["krungthai", "กรุงไทย", "กรงไทย"]
    },
    "kasikorn": {
        "display_name": "Kasikornbank / K PLUS / ธนาคารกสิกรไทย",
        "keywords": ["k+", "k plus", "กสิกร", "กสิกรไทย", "ธ.กสิกรไทย"]
    },
    "scb": {
        "display_name": "Siam Commercial Bank / SCB / ธนาคารไทยพาณิชย์",
        "keywords": ["scb", "ไทยพาณิชย์"]
    },
    "bangkok_bank": {
        "display_name": "Bangkok Bank / ธนาคารกรุงเทพ",
        "keywords": ["bangkok bank", "ธนาคารกรุงเทพ", "กรุงเทพ"]
    },
    "krungsri": {
        "display_name": "Krungsri / ธนาคารกรุงศรีอยุธยา",
        "keywords": ["krungsri", "กรุงศรี"]
    },
    "ttb": {
        "display_name": "TTB / ทหารไทยธนชาต",
        "keywords": ["ttb", "ทหารไทย", "ธนชาต"]
    },
    "promptpay": {
        "display_name": "PromptPay / พร้อมเพย์",
        "keywords": ["พร้อมเพย์", "promptpay", "prompt pay"]
    },
}


THAI_MONTHS = {
    "ม.ค": 1, "มค": 1,
    "ก.พ": 2, "กพ": 2,
    # Common OCR confusion for ก.พ. in Thai slips.
    # EasyOCR can read ก as n in "ก.พ.".
    "n.พ": 2, "nพ": 2, "n.พ.": 2,
    "N.พ": 2, "Nพ": 2, "N.พ.": 2,
    "มี.ค": 3, "มีค": 3,
    "เม.ย": 4, "เมย": 4,
    "พ.ค": 5, "พค": 5,
    "มิ.ย": 6, "มิย": 6,
    "ก.ค": 7, "กค": 7,
    "ส.ค": 8, "สค": 8,
    "ก.ย": 9, "กย": 9,
    "ต.ค": 10, "ตค": 10,
    # Common OCR confusion for ต.ค. where ต is read as Thai digit ๓.
    "๓.ค": 10, "๓ค": 10, "๓.ค.": 10,
    "พ.ย": 11, "พย": 11,
    "ธ.ค": 12, "ธค": 12,
    # Common OCR confusion for ธ.ค. where ธ is read as Arabic digit 5.
    # Example: "10 5.ค. 67 09:41" should be treated as "10 ธ.ค. 67 09:41".
    "5.ค": 12, "5ค": 12, "5.ค.": 12,
}


THAI_MONTH_CANONICAL = {
    1: "ม.ค.",
    2: "ก.พ.",
    3: "มี.ค.",
    4: "เม.ย.",
    5: "พ.ค.",
    6: "มิ.ย.",
    7: "ก.ค.",
    8: "ส.ค.",
    9: "ก.ย.",
    10: "ต.ค.",
    11: "พ.ย.",
    12: "ธ.ค.",
}


FIELD_ORDER = [
    "transfer_status",
    "source_app_or_bank",
    "reference_id",
    "transaction_date_raw",
    "transaction_time_raw",
    "transaction_datetime_iso_guess",
    "sender_name",
    "sender_bank",
    "sender_account",
    "receiver_name",
    "receiver_bank",
    "receiver_account",
    "amount",
    "fee",
    "note",
]


def make_field(value=None, raw_value=None, confidence=0.0, method="not_found", warnings=None, evidence_texts=None):
    return {
        "value": value,
        "raw_value": raw_value,
        "confidence": round(float(confidence), 4),
        "method": method,
        "warnings": warnings or [],
        "evidence_texts": evidence_texts or ([raw_value] if raw_value else []),
    }


def normalize_line(line: str) -> str:
    line = (line or "").strip()
    line = re.sub(r"\s+", " ", line)
    line = line.replace("จานวน", "จำนวน")
    line = line.replace("ค่ารรรมเนียม", "ค่าธรรมเนียม")
    line = line.replace("ค่ารรมเนียม", "ค่าธรรมเนียม")
    line = line.replace("กรงไทย", "กรุงไทย")
    return line.strip()


def split_lines(full_text: str) -> List[str]:
    return [normalize_line(line) for line in (full_text or "").splitlines() if normalize_line(line)]


def compact(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").lower())


def contains_any(text: str, keywords: List[str]) -> bool:
    low = (text or "").lower()
    return any(k.lower() in low for k in keywords)


def detect_bank_or_app(lines: List[str]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    full = "\n".join(lines).lower()
    candidates = []
    for bank_id, cfg in BANK_KEYWORDS.items():
        matched = [kw for kw in cfg["keywords"] if kw.lower() in full]
        if matched:
            candidates.append({
                "bank_id": bank_id,
                "display_name": cfg["display_name"],
                "matched_keywords": matched,
                "score": len(matched),
            })
    candidates.sort(key=lambda x: x["score"], reverse=True)
    if candidates:
        best = candidates[0]
        return make_field(best["display_name"], best["matched_keywords"], min(0.95, 0.55 + 0.15 * best["score"]), "keyword_bank_detection"), candidates
    return make_field(None, None, 0.0, "not_found", ["No bank/app keyword found."]), []


def is_bank_line(line: str) -> Optional[str]:
    line_low = (line or "").lower().strip()

    # PromptPay is not really a bank, but in this project it should behave like receiver_bank/source channel.
    if "พร้อมเพย์" in line_low or "promptpay" in line_low or "prompt pay" in line_low:
        return "PromptPay / พร้อมเพย์"

    # Avoid treating person names as bank names.
    if re.match(r"^(นาย|นาง|นางสาว|น\.ส\.)", line.strip()) and "ธ." not in line_low and "ธนาคาร" not in line_low:
        return None

    for bank_id, cfg in BANK_KEYWORDS.items():
        if bank_id == "promptpay":
            continue
        for kw in cfg["keywords"]:
            kw_low = kw.lower()
            if kw_low in line_low:
                # allow bank lines such as "กรุงไทย" or explicit marker "ธ."
                if line_low == kw_low or "ธ." in line_low or "ธนาคาร" in line_low or bank_id in ["krungthai", "krungsri", "scb"]:
                    return cfg["display_name"]
    return None


def transfer_status(lines: List[str]) -> Dict[str, Any]:
    for line in lines:
        if "โอนเงินสำเร็จ" in line:
            return make_field("success", line, 0.95, "success_keyword")
    for line in lines:
        if "โอนเงิน" in line and "สำ" in line:
            return make_field("success", line, 0.65, "fuzzy_success_keyword", ["Transfer status was fuzzy matched."])
    return make_field(None, None, 0.0, "not_found", ["Transfer status not found."])


def clean_reference_value(text: str) -> Optional[str]:
    if not text:
        return None
    s = text
    # Handle Thai and English reference labels, including OCR variant "n0" for "no".
    s = re.sub(r"^(รหัสอ้างอิง|เลขอ้างอิง|เลขที่อ้างอิง|เลขที่รายการ|reference\s*(?:no|n0|number)?|ref\s*(?:no|n0)?)\s*[:：.]?\s*", "", s, flags=re.I)
    s = re.sub(r"^(no|n0)\s*[:：.]?\s*", "", s, flags=re.I)
    s = re.sub(r"[^0-9A-Za-zก-๙\-_/]", "", s)
    # If OCR kept English label residue, remove it one more time.
    s = re.sub(r"^(reference|ref|no|n0)", "", s, flags=re.I)
    if len(s) >= 8:
        return s
    return None


def is_bad_global_reference_candidate(candidate: str, line: str) -> bool:
    c = compact(candidate)
    line_c = compact(line)

    # Bank logos and watermarks are often OCR'd as long Latin text. Do not let
    # those become reference IDs when there is no explicit reference label.
    watermark_tokens = [
        "krungthai",
        "rrungthai",
        "rungthai",
        "angthai",
        "kasikorn",
        "bangkokbank",
        "promptpay",
        "scb",
    ]
    if any(token in c or token in line_c for token in watermark_tokens):
        return True

    # Keep the unlabeled fallback conservative: it is meant for mixed
    # alphanumeric references, not pure logo/name OCR.
    if not re.search(r"[A-Za-z]", candidate) or not re.search(r"\d", candidate):
        return True

    return False


def reference_id(lines: List[str]) -> Dict[str, Any]:
    labels = ["รหัสอ้างอิง", "เลขอ้างอิง", "เลขที่อ้างอิง", "เลขที่รายการ", "reference", "ref"]
    for i, line in enumerate(lines):
        if contains_any(line, labels):
            after = re.sub(r".*?(รหัสอ้างอิง|เลขอ้างอิง|เลขที่อ้างอิง|เลขที่รายการ|reference\s*(?:no|n0|number)?|ref\s*(?:no|n0)?)\s*[:：.]?\s*", "", line, flags=re.I)
            val = clean_reference_value(after)
            if val:
                method = "reference_label_same_line_digits" if re.fullmatch(r"\d{10,25}", val) else "reference_label_same_line_preserve_alphanumeric"
                return make_field(val, line, 0.90, method)
            for j in range(i + 1, min(i + 4, len(lines))):
                val = clean_reference_value(lines[j])
                if val:
                    method = "reference_label_next_line_digits" if re.fullmatch(r"\d{10,25}", val) else "reference_label_next_line_preserve_alphanumeric"
                    return make_field(val, lines[j], 0.82, method)

    # fallback: long alphanumeric with both digits and letters, but avoid accounts.
    for line in lines:
        if is_account_line(line) or is_money_line(line):
            continue
        for m in re.findall(r"[A-Za-z0-9]{12,}", line):
            if is_bad_global_reference_candidate(m, line):
                continue
            return make_field(m, line, 0.45, "reference_global_alphanumeric_fallback", ["Reference ID found without label; check manually."])
    return make_field(None, None, 0.0, "not_found", ["Reference ID not found."])


def normalize_money_text(text: str) -> str:
    s = (text or "").replace(",", "")
    # Field-specific correction only.
    s = s.replace("O", "0").replace("o", "0").replace("D", "0").replace("d", "0")
    s = s.replace("๐", "0")
    return s


def find_money_with_warnings(text: str) -> Tuple[Optional[str], List[str]]:
    """Find a money-like number.

    If OCR attaches extra digits after a normal 2-decimal amount, keep the first
    two decimal digits instead of rounding. Example: 100,000.00748 -> 100000.00.
    """
    s = normalize_money_text(text)
    warnings = []

    # Accept normal 2 decimals and OCR-noisy >2 decimals.
    m = re.search(r"(?<!\d)(\d{1,3}(?:\d{3})*|\d+)\s*[.]\s*(\d{2,8})(?!\d)", s)
    if m:
        whole = m.group(1).replace(" ", "")
        decimals = m.group(2).replace(" ", "")
        if len(decimals) > 2:
            warnings.append(
                f"Money decimal part had extra OCR digits and was trimmed to 2 decimals: {whole}.{decimals} -> {whole}.{decimals[:2]}"
            )
        return f"{whole}.{decimals[:2]}", warnings

    return None, warnings


def find_money(text: str) -> Optional[str]:
    val, _warnings = find_money_with_warnings(text)
    return val


def is_money_line(line: str) -> bool:
    return find_money(line) is not None or "บาท" in (line or "")


def find_money_near_label(lines: List[str], labels: List[str], field_name: str) -> Dict[str, Any]:
    for i, line in enumerate(lines):
        if contains_any(line, labels):
            for j in range(i, min(i + 5, len(lines))):
                cand = lines[j]
                # avoid swallowing date/reference as amount/fee
                if j > i and contains_any(cand, ["วันที่", "รหัส", "เลขที่รายการ", "เลขที่อ้างอิง", "หมายเลขอ้างอิง", "reference", "ยอดเงินคงเหลือ", "คงเหลือ", "balance"]):
                    break
                val, money_warnings = find_money_with_warnings(cand.strip(" |｜"))
                if val is not None:
                    warnings = list(money_warnings)
                    if any(ch in cand for ch in ["o", "O", "d", "D"]):
                        warnings.append("OCR letters were corrected to digits for money field only.")
                    return make_field(val, cand, 0.90 if j > i else 0.84, f"{field_name}_label_neighbor", warnings)
                if field_name == "fee" and ("บาท" in cand.lower() or "thb" in cand.lower()) and re.search(r"[oOdD]", cand):
                    return make_field("0.00", cand, 0.55, "fee_zero_ocr_guess", ["Fee looked like OCR-corrupted zero amount; guessed 0.00."])
    return make_field(None, None, 0.0, "not_found", [f"{field_name} not found near label."])


def amount_top_fallback(lines: List[str]) -> Dict[str, Any]:
    """Fallback for slips where amount appears after status/date without a label.

    Example TTB:
        โอนเงินสำเร็จ
        10 ธ.ค. 67 09:41
        10,000.00
        ค่าธรรมเนียม
    """
    stop_keywords = ["ค่าธรรมเนียม", "fee", "จาก", "ไปยัง", "ไปที่", "reference", "รหัส", "เลขที่", "หมายเลข", "ยอดเงินคงเหลือ", "คงเหลือ", "balance"]
    start_idx = 0
    for i, line in enumerate(lines[:8]):
        if contains_any(line, ["โอนเงินสำเร็จ", "รายการสำเร็จ", "สำเร็จ"]):
            start_idx = i
            break

    for i in range(start_idx, min(start_idx + 8, len(lines))):
        line = lines[i]
        if contains_any(line, stop_keywords):
            break
        val, money_warnings = find_money_with_warnings(line)
        if val is not None:
            warnings = list(money_warnings)
            warnings.append("Amount found by top-position fallback without explicit amount label; review manually.")
            return make_field(val, line, 0.62, "amount_top_position_fallback", warnings)
        if has_thai_date_pattern(line) or has_time_pattern(line):
            continue
        if is_account_line(line):
            continue

    return make_field(None, None, 0.0, "not_found", ["amount not found by top-position fallback."])


def amount(lines: List[str]) -> Dict[str, Any]:
    field = find_money_near_label(lines, ["จำนวนเงิน", "จำนวน", "ยอดเงิน", "amount"], "amount")
    if field.get("value") not in [None, ""]:
        return field
    return amount_top_fallback(lines)


def fee(lines: List[str]) -> Dict[str, Any]:
    return find_money_near_label(lines, ["ค่าธรรมเนียม", "ธรรมเนียม", "fee"], "fee")


def extract_time(lines: List[str]) -> Dict[str, Any]:
    # Priority 1: time on the same line as a Thai date.
    for line in lines:
        if find_thai_date_match(line):
            m = re.search(r"\b([0-2]?\d)\s*[:.]\s*([0-5]\d)\b", line)
            if m:
                return make_field(f"{int(m.group(1)):02d}:{m.group(2)}", line, 0.90, "time_same_line_as_date")

    # Priority 2: time on the line immediately after a Thai date.
    for i, line in enumerate(lines[:-1]):
        if find_thai_date_match(line):
            m = re.search(r"\b([0-2]?\d)\s*[:.]\s*([0-5]\d)\b", lines[i + 1])
            if m:
                return make_field(f"{int(m.group(1)):02d}:{m.group(2)}", lines[i + 1], 0.86, "time_next_line_after_date")

    # Priority 3: normal fallback, but skip likely phone status-bar time before the slip status.
    status_idx = None
    for i, line in enumerate(lines[:8]):
        if contains_any(line, ["โอนเงินสำเร็จ", "ทำรายการสำเร็จ", "รายการสำเร็จ"]):
            status_idx = i
            break

    skipped_status_times = []
    for i, line in enumerate(lines):
        m = re.search(r"\b([0-2]?\d)\s*[:.]\s*([0-5]\d)\b", line)
        if not m:
            continue

        if status_idx is not None and i < status_idx and not find_thai_date_match(line):
            skipped_status_times.append(line)
            continue

        warnings = []
        if skipped_status_times:
            warnings.append("Ignored earlier standalone time before transfer status as likely phone screenshot/status-bar time.")
        return make_field(f"{int(m.group(1)):02d}:{m.group(2)}", line, 0.72, "time_regex_after_status_or_no_date", warnings)

    return make_field(None, None, 0.0, "not_found", ["Time not found."])


def normalize_month_token(month_text: str) -> Tuple[Optional[int], Optional[str], List[str]]:
    """Return (month_number, canonical_month_text, warnings)."""
    raw = (month_text or "").strip()
    cleaned = raw.replace(" ", "").replace("..", ".")
    cleaned_no_dot = cleaned.replace(".", "")

    month = THAI_MONTHS.get(cleaned) or THAI_MONTHS.get(cleaned_no_dot)
    warnings = []

    if month:
        canonical = THAI_MONTH_CANONICAL.get(month, cleaned)
        if cleaned not in [canonical.rstrip("."), canonical, cleaned_no_dot]:
            warnings.append(f"Month token was OCR-corrected from '{raw}' to '{canonical}'.")
        elif raw != canonical and month == 2 and raw.lower().startswith("n"):
            warnings.append(f"Month token was OCR-corrected from '{raw}' to '{canonical}'.")
        return month, canonical, warnings

    return None, None, [f"Unknown Thai month token: {raw}"]


def find_thai_date_match(text: str):
    """Find a Thai date-like pattern.

    Supports normal Thai months and known OCR month variants such as n.พ.
    The year can be 2 digits or Buddhist year 2540-2599.
    """
    if not text or is_money_line(text):
        return None

    # Strong BE-year clue: 2540-2599.
    m = re.search(
        r"(?<!\d)(\d{1,2})\s*([0-9ก-๙A-Za-z.]{1,8})\s*((?:25[4-9]\d)|(?:\d{2}))(?!\d)",
        text,
    )
    if m:
        return m

    return None


def extract_date(lines: List[str]) -> Dict[str, Any]:
    for i, line in enumerate(lines):
        m = find_thai_date_match(line)
        if m:
            day = int(m.group(1))
            month_token = m.group(2)
            year_text = m.group(3)
            month, canonical_month, month_warnings = normalize_month_token(month_token)

            # If the month is unknown but the year is a strong Buddhist year,
            # still return the raw date with lower confidence so parse_date_iso can explain failure.
            if month:
                corrected = f"{day:02d} {canonical_month} {year_text}"
                method = "thai_date_regex"
                confidence = 0.84
                warnings = []
                if corrected != line.strip():
                    method = "thai_date_ocr_corrected"
                    confidence = 0.72
                    warnings.extend(month_warnings)
                    warnings.append(f"Corrected date guess: {corrected}")
                return make_field(corrected, line, confidence, method, warnings, evidence_texts=[line, corrected])

            if re.fullmatch(r"25[4-9]\d", year_text):
                return make_field(line, line, 0.45, "thai_date_be_year_month_unknown", month_warnings)

        # Some OCR splits date and year into adjacent lines.
        if i + 1 < len(lines):
            combined = f"{line} {lines[i + 1]}"
            m = find_thai_date_match(combined)
            if m:
                day = int(m.group(1))
                month_token = m.group(2)
                year_text = m.group(3)
                month, canonical_month, month_warnings = normalize_month_token(month_token)
                if month:
                    corrected = f"{day:02d} {canonical_month} {year_text}"
                    warnings = month_warnings + [f"Corrected date guess: {corrected}"] if corrected != combined.strip() else []
                    return make_field(corrected, combined, 0.68, "thai_date_split_line_ocr_corrected", warnings, evidence_texts=[combined, corrected])

    return make_field(None, None, 0.0, "not_found", ["Date not found."])


def parse_date_iso(date_raw: Optional[str], time_raw: Optional[str]) -> Dict[str, Any]:
    if not date_raw or not time_raw:
        return make_field(None, None, 0.0, "not_available", ["Need both date and time to create ISO datetime."])

    m = find_thai_date_match(date_raw)
    if not m:
        return make_field(None, date_raw, 0.0, "date_parse_failed", ["Could not parse Thai date."])

    day = int(m.group(1))
    month_text = m.group(2)
    year_text = m.group(3)
    month, canonical_month, month_warnings = normalize_month_token(month_text)

    if not month:
        return make_field(None, date_raw, 0.0, "month_parse_failed", month_warnings)

    year = int(year_text)
    warnings = list(month_warnings)
    confidence = 0.76
    method = "thai_date_time_iso_guess"

    if 2540 <= year <= 2599:
        gregorian_year = year - 543
        method = "thai_be_year_date_time_iso_guess"
        confidence = 0.82
    elif 0 <= year < 100:
        # Thai slip shorthand. Interpret 66 as BE 2566.
        gregorian_year = (year + 2500) - 543
        method = "thai_two_digit_be_year_date_time_iso_guess"
        confidence = 0.68
        warnings.append(f"Two-digit year '{year_text}' was interpreted as Buddhist year {year + 2500}.")
    elif year > 2400:
        gregorian_year = year - 543
        method = "thai_be_year_date_time_iso_guess"
        confidence = 0.76
        warnings.append(f"Buddhist year '{year}' was converted by subtracting 543.")
    else:
        gregorian_year = year
        confidence = 0.65
        warnings.append(f"Year '{year}' was treated as Gregorian year.")

    corrected_raw = f"{day:02d} {canonical_month} {year_text}"
    raw_value = f"{date_raw} {time_raw}"
    if corrected_raw not in date_raw:
        warnings.append(f"Corrected date guess used for ISO parsing: {corrected_raw}")

    return make_field(
        f"{gregorian_year:04d}-{month:02d}-{day:02d}T{time_raw}",
        raw_value,
        confidence,
        method,
        warnings,
        evidence_texts=[date_raw, corrected_raw, time_raw],
    )


def clean_account_candidate(line: str) -> str:
    """Clean field-specific OCR noise before account detection.

    Examples:
        |888-8-8888-8| -> 888-8-8888-8
        ixxx-x-x8888-x -> xxx-x-x8888-x
    """
    s = (line or "").strip()

    # Remove common border/status OCR artifacts at the edges.
    s = s.strip(" |｜[](){}")

    # Sometimes a vertical border is recognized as i/l/I before a masked account.
    s = re.sub(r"^[iIl|]+(?=x{2,})", "", s.strip())

    # Keep only account-like characters and spaces.
    s = re.sub(r"[^0-9xX\-=\s]", "", s)

    # OCR may read dash as equals.
    s = re.sub(r"(?<=\d)\s*=\s*(?=\d)", "-", s)
    s = re.sub(r"\s*[-–]\s*", "-", s)
    # Krungsri-style masked accounts can OCR the final dash as a space:
    # xxx-9-12345 x -> xxx-9-12345-x.
    s = re.sub(r"(?<=[0-9xX])\s+(?=[xX]$)", "-", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def is_account_line(line: str) -> bool:
    # Transaction date/time can collapse to 10-13 digits after account cleanup
    # and should never be treated as an unmasked account.
    explicit_month_tokens = [
        "ม.ค", "ก.พ", "มี.ค", "เม.ย", "พ.ค", "มิ.ย",
        "ก.ค", "ส.ค", "ก.ย", "ต.ค", "พ.ย", "ธ.ค",
        "มค", "กพ", "มีค", "เมย", "พค", "มิย",
        "กค", "สค", "กย", "ตค", "พย", "ธค",
    ]
    if has_time_pattern(line) or contains_any(line, explicit_month_tokens):
        return False

    cleaned = clean_account_candidate(line)
    c = re.sub(r"\s+", "", cleaned)
    has_x = "x" in c.lower()
    has_digit = bool(re.search(r"\d", c))
    has_hyphen = "-" in c

    if has_x and has_digit:
        return True

    # Masked or unmasked bank-account-like pattern with hyphens:
    # xxx-x-x8888-x, 888-8-8888-8, etc.
    account_chars = re.sub(r"[^0-9xX\-]", "", c)
    digit_count = len(re.findall(r"\d", account_chars))
    if has_hyphen and len(account_chars) >= 7 and (has_x or digit_count >= 6):
        return True

    # Some slips show unmasked account numbers without separators.
    if re.fullmatch(r"\d{10,13}", c):
        return True

    # Spaced PromptPay/account-like text such as "x xxxx xxxx5 65 0".
    if has_x and digit_count >= 2 and len(account_chars.replace("-", "")) >= 8:
        return True

    return False


def normalize_account(line: str) -> str:
    return clean_account_candidate(line)


def has_thai_date_pattern(line: str) -> bool:
    return bool(re.search(r"\d{1,2}\s*[0-9ก-๙A-Za-z.]{1,8}\s*(?:25[4-9]\d|\d{2,4})", line or ""))


def has_time_pattern(line: str) -> bool:
    if re.search(r"\b[0-2]?\d\s*[:.]\s*[0-5]\d\b", line or ""):
        return True
    # Thai slips often include time suffix "น.".
    if re.search(r"\b[0-2]?\d\s*[:.]\s*[0-5]\d\s*น\.?", line or ""):
        return True
    return False


def strip_date_time_prefix_before_name(line: str) -> str:
    """Clean OCR lines like '29 พ.ค. 66 11:00 น. นาย ปฏิญญา ม'.

    Keep text starting from the first Thai person-title token when a date/time prefix
    was merged into the same OCR line.
    """
    raw = (line or "").strip()
    if not raw:
        return raw

    title_match = re.search(r"(นาย|นางสาว|นาง|น\.ส\.)\s*", raw)
    if not title_match:
        return raw

    prefix = raw[:title_match.start()]
    if has_thai_date_pattern(prefix) or has_time_pattern(prefix) or re.search(r"\d", prefix):
        return raw[title_match.start():].strip()

    return raw


def is_definitely_not_name_line(line: str) -> bool:
    raw = line or ""
    stripped = raw.strip()
    if not stripped:
        return True

    # Pure date/time lines should never be used as person names.
    if has_thai_date_pattern(stripped) and not re.search(r"(นาย|นางสาว|นาง|น\.ส\.)", stripped):
        return True
    if has_time_pattern(stripped) and not re.search(r"(นาย|นางสาว|นาง|น\.ส\.)", stripped):
        return True
    if stripped in ["+", "i+", "k+", "K+"]:
        return True
    return False


def is_name_like(line: str) -> bool:
    if not line:
        return False

    cleaned = strip_date_time_prefix_before_name(line)

    if is_definitely_not_name_line(cleaned):
        return False
    if is_account_line(cleaned):
        return False
    if is_bank_line(cleaned):
        return False
    if is_money_line(cleaned):
        return False
    if contains_any(cleaned, ["โอนเงิน", "รหัส", "อ้างอิง", "เลขที่", "จำนวน", "ค่าธรรมเนียม", "วันที่", "บาท", "จาก", "ไปยัง", "ไปที่", "สแกนตรวจสอบ", "สแกน", "ตรวจสอบ", "โอนเพิ่ม", "แชร์", "ยอดคงเหลือ", "กลับหน้าหลัก", "category"]):
        return False
    # Date/time mixed with no Thai title should not become a name.
    if (has_thai_date_pattern(cleaned) or has_time_pattern(cleaned)) and not re.search(r"(นาย|นางสาว|นาง|น\.ส\.)", cleaned):
        return False
    # Long digit sequences are usually references/accounts, not names.
    if re.search(r"\d{4,}", cleaned):
        return False

    # Thai person/organization names.
    if re.search(r"[ก-๙]", cleaned):
        return True

    # Some slips show receiver names in English uppercase/lowercase, e.g. SRITHANYA.
    if re.search(r"[A-Za-z]", cleaned) and len(re.sub(r"[^A-Za-z]", "", cleaned)) >= 2:
        return True

    return False


def find_section_bounds(lines: List[str], start_labels: List[str], end_labels: List[str]) -> Optional[Tuple[int, int]]:
    start = None
    for i, line in enumerate(lines):
        if any(compact(line) == compact(label) or compact(label) in compact(line) for label in start_labels):
            start = i
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if any(compact(lines[j]) == compact(label) or compact(label) in compact(lines[j]) for label in end_labels):
            end = j
            break
    return start, end


def parse_party_block(block_lines: List[str], role: str) -> Dict[str, Any]:
    names = []
    bank = None
    account = None

    for line in block_lines:
        if not bank:
            bank = is_bank_line(line)
        if not account and is_account_line(line):
            account = normalize_account(line)
        if is_name_like(line):
            cleaned_name = strip_date_time_prefix_before_name(line)
            if cleaned_name and not is_definitely_not_name_line(cleaned_name):
                names.append(cleaned_name)

    # Prefer the last 1-2 consecutive name-like lines before bank/account.
    name = " ".join(names).strip() if names else None

    result = {
        "name": name,
        "bank": bank,
        "account": account,
        "raw_lines": block_lines,
    }
    return result


def extract_account_group_sequence(lines: List[str]) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    """Fallback for slips without explicit จาก/ไปยัง labels.

    Handles both common orders:
        name / bank / account
        name / account / bank

    The second form appears in some TTB-style slips.
    """
    groups = []
    warnings = []

    for account_idx, line in enumerate(lines):
        if not is_account_line(line):
            continue

        bank_value = None
        bank_line_text = None
        name_lines = []

        # Search for a nearby bank/channel line above or below the account.
        for j in range(account_idx - 1, max(-1, account_idx - 5), -1):
            if is_account_line(lines[j]):
                break
            bank_candidate = is_bank_line(lines[j])
            if bank_candidate:
                bank_value = bank_candidate
                bank_line_text = lines[j]
                break

        if not bank_value:
            for j in range(account_idx + 1, min(len(lines), account_idx + 4)):
                if is_account_line(lines[j]):
                    break
                bank_candidate = is_bank_line(lines[j])
                if bank_candidate:
                    bank_value = bank_candidate
                    bank_line_text = lines[j]
                    break

        # Collect 1-2 nearby name lines above the account. Skip bank lines but
        # stop at another account, amount, reference, or clear non-name section.
        for j in range(account_idx - 1, max(-1, account_idx - 5), -1):
            if is_account_line(lines[j]):
                break
            if is_bank_line(lines[j]):
                continue
            if is_money_line(lines[j]):
                break
            if contains_any(lines[j], ["reference", "รหัส", "อ้างอิง", "เลขที่", "จำนวน", "ค่าธรรมเนียม"]):
                break

            if is_name_like(lines[j]):
                cleaned_name = strip_date_time_prefix_before_name(lines[j])
                if cleaned_name and not is_definitely_not_name_line(cleaned_name):
                    name_lines.insert(0, cleaned_name)
            elif name_lines:
                break
            elif is_definitely_not_name_line(lines[j]):
                break

        # Require at least an account and either bank or name to avoid over-matching noise.
        if bank_value or name_lines:
            name = " ".join(name_lines).strip() if name_lines else None
            if not name and bank_line_text and "กรุงศรี" in bank_line_text and compact(bank_line_text) != compact("กรุงศรี"):
                name = bank_line_text
            groups.append({
                "name": name,
                "bank": bank_value,
                "account": normalize_account(line),
                "account_line_index": account_idx,
                "method": "account_group_sequence_rule",
            })

    # Deduplicate repeated account lines if OCR creates duplicates.
    deduped = []
    seen_accounts = set()
    for group in groups:
        acc_key = compact(group.get("account") or "")
        if acc_key in seen_accounts:
            continue
        seen_accounts.add(acc_key)
        deduped.append(group)

    if len(deduped) >= 2:
        return deduped[0], deduped[1], warnings

    warnings.append("Account-group sequence fallback could not find two complete party groups.")
    sender = deduped[0] if len(deduped) >= 1 else {}
    receiver = deduped[1] if len(deduped) >= 2 else {}
    return sender, receiver, warnings


def extract_parties(lines: List[str]) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    warnings = []
    sender_bounds = find_section_bounds(lines, ["จาก"], ["ไปยัง", "ไปที่", "จำนวนเงิน", "จำนวน"])
    receiver_bounds = find_section_bounds(lines, ["ไปยัง", "ไปที่"], ["จำนวนเงิน", "จำนวน", "ค่าธรรมเนียม", "วันที่ทำรายการ", "บันทึกช่วยจำ", "หมายเลขอ้างอิง", "เลขที่อ้างอิง"])

    if sender_bounds:
        s_start, s_end = sender_bounds
        sender_block = lines[s_start + 1:s_end]
    else:
        sender_block = []

    if receiver_bounds:
        r_start, r_end = receiver_bounds
        receiver_block = lines[r_start + 1:r_end]
    else:
        receiver_block = []

    sender = parse_party_block(sender_block, "sender") if sender_block else {}
    receiver = parse_party_block(receiver_block, "receiver") if receiver_block else {}

    # Fallback by repeated account groups if section labels failed or are incomplete.
    if not sender.get("name") or not sender.get("account") or not receiver.get("name") or not receiver.get("account"):
        seq_sender, seq_receiver, seq_warnings = extract_account_group_sequence(lines)

        if (not sender.get("name") or not sender.get("account")) and seq_sender:
            sender = {**sender, **{k: v for k, v in seq_sender.items() if v}}
            sender["method"] = "account_group_sequence_rule"

        if (not receiver.get("name") or not receiver.get("account")) and seq_receiver:
            receiver = {**receiver, **{k: v for k, v in seq_receiver.items() if v}}
            receiver["method"] = "account_group_sequence_rule"

        # Only report fallback warning if it was needed and still failed.
        if (not sender.get("account") or not receiver.get("account")):
            warnings.extend(seq_warnings)

    if not sender.get("account") or not receiver.get("account"):
        accounts = [(i, normalize_account(line)) for i, line in enumerate(lines) if is_account_line(line)]
        if len(accounts) >= 2:
            if not sender.get("account"):
                sender["account"] = accounts[0][1]
            if not receiver.get("account"):
                receiver["account"] = accounts[1][1]
        else:
            warnings.append("Could not find two account-like lines.")

    if not sender_block:
        warnings.append("Sender section label 'จาก' not found; account-group fallback may be used.")
    if not receiver_block:
        warnings.append("Receiver section label 'ไปยัง' not found; account-group fallback may be used.")

    return sender, receiver, warnings


def rect_from_bbox_points(bbox_points):
    xs = [float(p[0]) for p in bbox_points]
    ys = [float(p[1]) for p in bbox_points]
    return [min(xs), min(ys), max(xs), max(ys)]


def find_field_evidence_boxes(fields: Dict[str, Dict[str, Any]], ocr_items: List[Dict[str, Any]], image_width: int, image_height: int):
    boxes = []
    for field_name, field in fields.items():
        evidence_texts = field.get("evidence_texts", [])
        if not evidence_texts:
            continue
        for item in ocr_items:
            text_clean = compact(item.get("text", ""))
            for ev in evidence_texts:
                ev_clean = compact(str(ev))
                if not ev_clean:
                    continue
                if ev_clean in text_clean or text_clean in ev_clean:
                    rect = rect_from_bbox_points(item.get("bbox", []))
                    boxes.append({
                        "field_name": field_name,
                        "source": "generic_rule_ocr_text",
                        "method": field.get("method"),
                        "confidence": field.get("confidence", 0.0),
                        "bbox_pixel": [round(v, 2) for v in rect],
                        "bbox_norm": [round(v, 6) for v in _normalize_rect(rect, image_width, image_height)],
                        "text": item.get("text"),
                    })
                    break
    return boxes


def qr_boxes(qr_codes: List[Dict[str, Any]]):
    return [{
        "field_name": "qr_code",
        "source": "qr_detector",
        "method": qr.get("method"),
        "confidence": 1.0,
        "bbox_pixel": qr.get("bbox_pixel"),
        "bbox_norm": qr.get("bbox_norm"),
        "text": qr.get("data"),
    } for qr in qr_codes]


def is_note_stop_line(line: str) -> bool:
    """Stop note capture at QR/instruction text or next major slip section."""
    stop_keywords = [
        "ผู้รับเงินสามารถสแกน",
        "สแกนคิวอาร์",
        "คิวอาร์โค้ด",
        "คิวอาร์โคัด",
        "ตรวจสอบสถานะ",
        "ตรวจสอบสถานะการโอน",
        "verified",
        "veritied",
        "จำนวนเงิน",
        "จำนวน:",
        "ค่าธรรมเนียม",
        "วันที่ทำรายการ",
        "รหัสอ้างอิง",
        "เลขที่รายการ",
        "จาก",
        "ไปยัง",
    ]
    return contains_any(line, stop_keywords)


def clean_note_candidate(line: str) -> str:
    value = (line or "").strip()
    value = re.sub(r"^(บันทึกช่วยจำ|หมายเหตุ|note|memo)\s*[:：]?\s*", "", value, flags=re.I)
    value = value.strip(" :：")
    return value.strip()


def extract_note(lines: List[str]) -> Dict[str, Any]:
    """Low-priority note extraction.

    Strictly requires a note label such as บันทึกช่วยจำ / หมายเหตุ / note / memo.
    It never searches for arbitrary bottom text, so it should not affect amount/date/name rules.
    """
    label_keywords = ["บันทึกช่วยจำ", "หมายเหตุ", "note", "memo"]

    for i, line in enumerate(lines):
        if not contains_any(line, label_keywords):
            continue

        # Same-line form: "บันทึกช่วยจำ: สมัครสมาชิก ..."
        same_line = clean_note_candidate(line)
        if same_line and same_line != line.strip() and not is_note_stop_line(same_line):
            return make_field(
                same_line,
                line,
                0.82,
                "note_label_same_line",
                ["Note is low-priority metadata; review if used for business decisions."],
                evidence_texts=[line, same_line],
            )

        # Next-line or short multi-line form:
        # บันทึกช่วยจำ
        # ชาญ
        note_lines = []
        for j in range(i + 1, min(i + 5, len(lines))):
            candidate = clean_note_candidate(lines[j])
            if not candidate:
                continue
            if is_note_stop_line(candidate):
                break
            if is_money_line(candidate) or is_account_line(candidate):
                break
            if has_thai_date_pattern(candidate) or has_time_pattern(candidate):
                break

            note_lines.append(candidate)

            # Most slip notes are one line. Allow at most two lines to avoid swallowing QR text.
            if len(note_lines) >= 2:
                break

        if note_lines:
            value = " ".join(note_lines).strip()
            confidence = 0.76 if len(note_lines) == 1 else 0.68
            return make_field(
                value,
                "\n".join(note_lines),
                confidence,
                "note_label_next_line",
                ["Note is low-priority metadata; OCR may be incomplete or noisy."],
                evidence_texts=[line] + note_lines,
            )

        return make_field(
            None,
            line,
            0.0,
            "note_label_found_but_empty",
            ["Note label was found, but no safe note value was captured."],
            evidence_texts=[line],
        )

    return make_field(None, None, 0.0, "not_found", ["Note label was not found."])


def extract_generic_rules_from_full_text(full_text: str, ocr_items: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    lines = split_lines(full_text)
    warnings = []

    bank_field, bank_candidates = detect_bank_or_app(lines)
    status_field = transfer_status(lines)
    ref_field = reference_id(lines)
    amount_field = amount(lines)
    fee_field = fee(lines)
    note_field = extract_note(lines)
    date_field = extract_date(lines)
    time_field = extract_time(lines)
    datetime_field = parse_date_iso(date_field.get("value"), time_field.get("value"))

    sender, receiver, party_warnings = extract_parties(lines)
    warnings.extend(party_warnings)

    fields = {
        "transfer_status": status_field,
        "source_app_or_bank": bank_field,
        "reference_id": ref_field,
        "transaction_date_raw": date_field,
        "transaction_time_raw": time_field,
        "transaction_datetime_iso_guess": datetime_field,
        "sender_name": make_field(sender.get("name"), sender.get("name"), 0.65 if sender.get("name") else 0.0, sender.get("method", "sender_section_rule")),
        "sender_bank": make_field(sender.get("bank"), sender.get("bank"), 0.75 if sender.get("bank") else 0.0, sender.get("method", "sender_section_bank_or_channel_rule")),
        "sender_account": make_field(sender.get("account"), sender.get("account"), 0.85 if sender.get("account") else 0.0, sender.get("method", "sender_section_account_rule")),
        "receiver_name": make_field(receiver.get("name"), receiver.get("name"), 0.65 if receiver.get("name") else 0.0, receiver.get("method", "receiver_section_rule")),
        "receiver_bank": make_field(receiver.get("bank"), receiver.get("bank"), 0.75 if receiver.get("bank") else 0.0, receiver.get("method", "receiver_section_bank_or_channel_rule")),
        "receiver_account": make_field(receiver.get("account"), receiver.get("account"), 0.85 if receiver.get("account") else 0.0, receiver.get("method", "receiver_section_account_rule")),
        "amount": amount_field,
        "fee": fee_field,
        "note": note_field,
    }

    missing = [k for k in FIELD_ORDER if fields.get(k, {}).get("value") in [None, ""]]
    low_confidence = [k for k, f in fields.items() if f.get("value") not in [None, ""] and f.get("confidence", 0) < 0.60]

    for k, f in fields.items():
        for w in f.get("warnings", []):
            warnings.append(f"{k}: {w}")

    return {
        "status": "partial_success" if missing else "success",
        "document_type": "bank_transfer_slip_generic_rules_v1",
        "detected_bank_candidates": bank_candidates,
        "fields": fields,
        "missing_fields": missing,
        "low_confidence_fields": low_confidence,
        "warnings": warnings,
        "line_count": len(lines),
        "normalized_lines": lines,
        "raw_full_text": full_text,
    }


def run_generic_rule_ocr(image_path: str) -> Dict[str, Any]:
    with Image.open(image_path) as img:
        image_width, image_height = img.size

    ocr_result = run_ocr(image_path)
    full_text = ocr_result.get("result", {}).get("full_text", "")
    ocr_items = ocr_result.get("result", {}).get("items", [])

    extraction = extract_generic_rules_from_full_text(full_text, ocr_items)
    qr_codes = _detect_qr_codes(image_path, image_width, image_height)

    evidence_boxes = find_field_evidence_boxes(extraction.get("fields", {}), ocr_items, image_width, image_height)
    evidence_boxes.extend(qr_boxes(qr_codes))

    warnings = []
    if not qr_codes:
        warnings.append("No QR code detected or QR code could not be decoded.")

    return {
        "status": "success",
        "mode": "generic_rules_ocr_v1",
        "pipeline": [
            "full_image_easyocr_once",
            "raw_full_text_rule_extraction",
            "promptpay_as_bank_or_channel_keyword",
            "qr_extraction",
            "evidence_boxes",
        ],
        "filename": os.path.basename(image_path),
        "input_image": {
            "filename": os.path.basename(image_path),
            "width": image_width,
            "height": image_height,
        },
        "extraction": extraction,
        "qr_codes": qr_codes,
        "evidence_boxes": evidence_boxes,
        "ocr_result": ocr_result,
        "warnings": warnings,
        "limitations": [
            "Rule-based extraction depends on OCR quality and keyword coverage.",
            "PromptPay is treated as receiver/sender bank_or_channel when it appears inside the party section.",
            "Some slips may conflict with rules; uncertain fields should be reviewed by a human.",
            "No database and no template boxes are used on this page.",
        ],
    }
