import json
import os
import re
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple


BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
BANK_CONFIG_PATH = os.path.join(BASE_DIR, "configs", "bank_keywords.json")


FIELD_NAMES = [
    "transfer_status",
    "slip_format_guess",
    "source_app_or_bank",
    "reference_id",
    "amount",
    "fee",
    "transaction_date_raw",
    "transaction_time_raw",
    "transaction_datetime_iso_guess",
    "sender_name",
    "sender_bank",
    "sender_account",
    "receiver_name",
    "receiver_bank",
    "receiver_account",
]


THAI_MONTHS = {
    "ม.ค": 1,
    "มค": 1,
    "ก.พ": 2,
    "กพ": 2,
    "n.พ": 2,   # common OCR error in the provided sample
    "nพ": 2,
    "มี.ค": 3,
    "มีค": 3,
    "เม.ย": 4,
    "เมย": 4,
    "พ.ค": 5,
    "พค": 5,
    "มิ.ย": 6,
    "มิย": 6,
    "ก.ค": 7,
    "กค": 7,
    "ส.ค": 8,
    "สค": 8,
    "ก.ย": 9,
    "กย": 9,
    "ต.ค": 10,
    "ตค": 10,
    "พ.ย": 11,
    "พย": 11,
    "ธ.ค": 12,
    "ธค": 12,
}


STOP_NAME_KEYWORDS = [
    "โอนเงิน", "สำเร็จ", "รหัส", "อ้างอิง", "เลขที่", "รายการ", "จำนวน", "ค่าธรรมเนียม",
    "วันที่", "verified", "veritied", "k+", "krungthai", "กรุงไทย", "กรงไทย",
]


def load_bank_config() -> Dict[str, Any]:
    try:
        with open(BANK_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"banks": []}


def normalize_line(line: str) -> str:
    line = line.strip()
    line = re.sub(r"\s+", " ", line)
    line = line.replace("เลขที่ รายการ", "เลขที่รายการ")
    line = line.replace("เลขที่ รายการ:", "เลขที่รายการ:")
    line = line.replace("veritied", "verified")
    line = line.replace("กรงไทย", "กรุงไทย")
    # Keep OCR text mostly raw, but normalize common spacing around Thai bank-slip labels.
    line = line.replace("จานวน", "จำนวน")
    line = line.replace("เง็น", "เงิน")
    line = line.replace("ค่ารรรมเนียม", "ค่าธรรมเนียม")
    line = line.replace("ค่ารรมเนียม", "ค่าธรรมเนียม")
    return line.strip()


def split_lines(full_text: str) -> List[str]:
    return [normalize_line(line) for line in full_text.splitlines() if normalize_line(line)]


def make_field(value=None, raw_value=None, confidence=0.0, method="not_extracted", warnings=None):
    return {
        "value": value,
        "raw_value": raw_value,
        "confidence": round(float(confidence), 4),
        "method": method,
        "warnings": warnings or [],
    }


def contains_any(text: str, keywords: List[str]) -> bool:
    low = text.lower()
    return any(k.lower() in low for k in keywords)


def compact_text(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def fuzzy_ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, compact_text(a), compact_text(b)).ratio()


def fuzzy_contains_label(text: str, keywords: List[str], threshold: float = 0.68) -> bool:
    """Return True when a line is close to an expected label.

    This is intentionally used only for labels such as จำนวนเงิน or ค่าธรรมเนียม,
    not for final field values.
    """
    if contains_any(text, keywords):
        return True
    low = compact_text(text)
    for kw in keywords:
        kwc = compact_text(kw)
        if not kwc:
            continue
        if fuzzy_ratio(low, kwc) >= threshold:
            return True
    return False


def is_amount_like_line(line: str) -> bool:
    """Reject money/amount lines when extracting dates."""
    low = line.lower().strip()
    if "บาท" in low:
        return True
    cleaned = normalize_numeric_text_for_money(low)
    if re.search(r"(?<!\d)\d+[.]\d{2}(?!\d)", cleaned):
        return True
    if contains_any(low, ["จำนวน", "จำนวนเงิน", "ค่าธรรมเนียม"]):
        return True
    return False


def detect_bank_or_app(lines: List[str]) -> Tuple[Dict[str, Any], List[str]]:
    config = load_bank_config()
    full = "\n".join(lines).lower()
    candidates = []
    warnings = []

    for bank in config.get("banks", []):
        score = 0
        matched = []
        for kw in bank.get("keywords", []):
            if kw.lower() in full:
                score += 1
                matched.append(kw)
        if score > 0:
            candidates.append({
                "bank_id": bank.get("bank_id"),
                "display_name": bank.get("display_name"),
                "score": score,
                "matched_keywords": matched,
            })

    candidates.sort(key=lambda x: x["score"], reverse=True)

    if not candidates:
        warnings.append("Could not confidently detect bank/app from configured keywords.")
        return make_field(None, None, 0.0, "bank_keyword_detection", warnings), []

    best = candidates[0]
    confidence = min(0.95, 0.45 + best["score"] * 0.15)
    return make_field(best["display_name"], best["matched_keywords"], confidence, "bank_keyword_detection"), candidates


def guess_slip_format(lines: List[str]) -> Dict[str, Any]:
    full = "\n".join(lines).lower()
    if "k+" in full or "กสิกร" in full:
        return make_field("kplus_like", "k+ / กสิกร keyword", 0.85, "keyword_format_guess")
    if "krungthai" in full or "กรุงไทย" in full or "กรงไทย" in full:
        return make_field("krungthai_like", "krungthai / กรุงไทย keyword", 0.85, "keyword_format_guess")
    return make_field("generic_bank_slip", None, 0.35, "generic_fallback")


def extract_transfer_status(lines: List[str]) -> Dict[str, Any]:
    target = "โอนเงินสำเร็จ"
    for line in lines:
        if target in line:
            return make_field("success", line, 0.95, "keyword")
        # Fuzzy fallback for common OCR variants such as "โอนเงินสำเรือ".
        if "โอนเงิน" in line and fuzzy_ratio(line, target) >= 0.62:
            return make_field("success", line, 0.65, "fuzzy_transfer_status", ["Transfer status was fuzzy-matched from OCR text."])
    return make_field(None, None, 0.0, "not_found", ["Transfer status keyword was not found."])


def normalize_reference_candidate(text: str) -> str:
    # Used only for reference-id candidates. Do not use globally.
    trans = str.maketrans({
        "O": "0", "o": "0",
        "I": "1", "l": "1", "|": "1", "!": "1", "]": "1", "[": "1",
        "S": "5", "s": "5",
    })
    return text.translate(trans)


def extract_reference_id(lines: List[str]) -> Dict[str, Any]:
    label_keywords = ["เลขที่รายการ", "เลขที่ รายการ", "รหัสอ้างอิง", "อ้างอิง", "reference"]

    def find_ref_in_candidate(candidate: str) -> Optional[str]:
        norm = normalize_reference_candidate(candidate)
        compact = norm.replace(" ", "")
        # OCR may insert punctuation/letters inside a long reference line. Prefer a digit-only
        # reconstruction when it is longer than the longest continuous digit run.
        digit_runs = re.findall(r"\d{10,30}", compact)
        longest_run = max(digit_runs, key=len) if digit_runs else None
        digits_only = re.sub(r"\D", "", norm)
        if 10 <= len(digits_only) <= 30 and not is_account_line(candidate) and "บาท" not in candidate:
            if longest_run is None or len(digits_only) > len(longest_run):
                return digits_only
        if longest_run:
            return longest_run
        return None

    for i, line in enumerate(lines):
        if fuzzy_contains_label(line, label_keywords, threshold=0.62):
            ref = find_ref_in_candidate(line)
            if ref:
                return make_field(ref, line, 0.88, "label_same_line_normalized")

            for j in range(i + 1, min(i + 4, len(lines))):
                ref = find_ref_in_candidate(lines[j])
                if ref:
                    return make_field(ref, lines[j], 0.86, "label_neighbor_next_lines_normalized")

    # Global fallback, but avoid obvious money/account/date lines.
    for line in lines:
        if is_account_line(line) or is_amount_like_line(line):
            continue
        ref = find_ref_in_candidate(line)
        if ref:
            return make_field(ref, line, 0.50, "global_regex_fallback_normalized", ["Reference ID found without label context."])

    return make_field(None, None, 0.0, "not_found", ["Reference ID could not be extracted."])

def normalize_numeric_text_for_money(text: str) -> str:
    # Only call this for fields expected to be money.
    text = text.strip()
    text = text.replace(",", "")
    text = text.replace("O", "0").replace("o", "0")
    text = text.replace("D", "0").replace("d", "0")
    text = text.replace("๐", "0")
    text = text.replace("บาท", " บาท")
    text = re.sub(r"\s+", " ", text)
    return text


def find_money_in_text(text: str) -> Optional[str]:
    cleaned = normalize_numeric_text_for_money(text)
    # Allow 101.00, 888.00, 1,200.00 after comma removal.
    match = re.search(r"(?<!\d)(\d+\s*[\.]\s*\d{2})(?!\d)", cleaned)
    if match:
        return match.group(1).replace(" ", "")
    return None


def looks_like_amount_label(line: str) -> bool:
    return fuzzy_contains_label(line, ["จำนวนเงิน", "จำนวน", "จํานวนเงิน"], threshold=0.62)


def looks_like_fee_label(line: str) -> bool:
    return fuzzy_contains_label(line, ["ค่าธรรมเนียม", "ธรรมเนียม"], threshold=0.58)


def extract_money_near_label(lines: List[str], label_checker, field_name: str) -> Dict[str, Any]:
    for i, line in enumerate(lines):
        if label_checker(line):
            # Same line first, then next lines. Stop early if a different strong label begins.
            for j in range(i, min(i + 5, len(lines))):
                candidate = lines[j]
                if j != i:
                    if field_name == "amount" and looks_like_fee_label(candidate):
                        break
                    if field_name == "fee" and ("วันที่" in candidate or "รายการ" in candidate or "รหัส" in candidate):
                        break

                money = find_money_in_text(candidate)
                if money is not None:
                    warnings = []
                    if any(ch in candidate for ch in ["o", "O", "d", "D"]):
                        warnings.append("OCR letters were corrected to digits for money field only.")
                    return make_field(money, candidate, 0.88 if j != i else 0.84, f"{field_name}_label_neighbor", warnings)

                # Fee OCR often becomes o.od / ddd. If near fee label and line contains บาท but no numeric decimal,
                # provide a conservative low-confidence 0.00 candidate.
                if field_name == "fee" and "บาท" in candidate:
                    compact = re.sub(r"[^0oOdD]", "", candidate)
                    if compact and all(ch in "0oOdD" for ch in compact):
                        return make_field("0.00", candidate, 0.45, "fee_label_neighbor_zero_guess", ["Fee looked like OCR-corrupted zero amount; guessed 0.00."])

    return make_field(None, None, 0.0, "not_found", [f"{field_name} could not be extracted near label."])


def extract_amount(lines: List[str]) -> Dict[str, Any]:
    return extract_money_near_label(lines, looks_like_amount_label, "amount")


def extract_fee(lines: List[str]) -> Dict[str, Any]:
    return extract_money_near_label(lines, looks_like_fee_label, "fee")

def extract_time(lines: List[str]) -> Dict[str, Any]:
    for line in lines:
        match = re.search(r"\b([0-2]?\d)\s*[:.]\s*([0-5]\d)\b", line)
        if match:
            value = f"{int(match.group(1)):02d}:{match.group(2)}"
            return make_field(value, line, 0.80, "time_regex")

    # Low-confidence fallback for OCR like "15 4[]" -> 15:40.
    for line in lines:
        cleaned = line.replace("[]", "0").replace("[", "0").replace("]", "0").replace("O", "0").replace("o", "0")
        match = re.search(r"\b([0-2]?\d)\s+([0-5]?[0-9])\b", cleaned)
        if match:
            minute = match.group(2)
            if len(minute) == 1:
                minute = minute + "0"
            value = f"{int(match.group(1)):02d}:{minute}"
            return make_field(value, line, 0.45, "ocr_corrupted_time_guess", ["Time was guessed from corrupted OCR text."])

    return make_field(None, None, 0.0, "not_found", ["Time could not be extracted."])


def normalize_ocr_date_line(line: str) -> str:
    # Used only inside date parsing, not global OCR text.
    out = line.strip()
    out = out.replace("n.w", "ก.พ").replace("n.พ", "ก.พ").replace("ก.w", "ก.พ")
    out = out.replace("ม ค", "ม.ค").replace("ก พ", "ก.พ")
    # Common OCR for 01 at the beginning of a date line. Keep conservative.
    out = re.sub(r"^di\b", "01", out, flags=re.IGNORECASE)
    out = re.sub(r"^d1\b", "01", out, flags=re.IGNORECASE)
    out = re.sub(r"^l1\b", "11", out, flags=re.IGNORECASE)
    return out


def extract_date(lines: List[str]) -> Dict[str, Any]:
    date_label_idx = None
    for i, line in enumerate(lines):
        if fuzzy_contains_label(line, ["วันที่ทำรายการ", "วันที่", "วันทีทำรายการ"], threshold=0.52):
            date_label_idx = i
            break

    search_indices = list(range(len(lines)))
    if date_label_idx is not None:
        search_indices = list(range(date_label_idx + 1, min(date_label_idx + 5, len(lines)))) + search_indices

    # Strict Thai month tokens. This prevents amount lines such as 101.00 บาท from becoming date=01.00.
    month_pat = r"(ม\.?ค\.?|ก\.?พ\.?|มี\.?ค\.?|เม\.?ย\.?|พ\.?ค\.?|มิ\.?ย\.?|ก\.?ค\.?|ส\.?ค\.?|ก\.?ย\.?|ต\.?ค\.?|พ\.?ย\.?|ธ\.?ค\.?|n\.?พ\.?|n\.?w\.?)"

    seen = set()
    for i in search_indices:
        if i in seen:
            continue
        seen.add(i)
        raw_line = lines[i]
        if is_amount_like_line(raw_line):
            continue
        line = normalize_ocr_date_line(raw_line)

        match = re.search(rf"\b([0-3]?\d)\s*{month_pat}\s*(\d{{2,4}})\b", line, flags=re.IGNORECASE)
        if match:
            raw = match.group(0)
            confidence = 0.82 if date_label_idx is not None and i > date_label_idx else 0.68
            warnings = []
            if raw_line != line:
                warnings.append("Date line was normalized from OCR-corrupted text.")
            return make_field(raw, raw_line, confidence, "thai_date_regex_strict", warnings)

        # Slash/dash date fallback, e.g. 01/02/2565. Reject decimal money by requiring / or -.
        match2 = re.search(r"\b([0-3]?\d)[/-]([01]?\d)[/-](\d{2,4})\b", line)
        if match2:
            raw = match2.group(0)
            confidence = 0.78 if date_label_idx is not None and i > date_label_idx else 0.62
            return make_field(raw, raw_line, confidence, "slash_date_regex")

    return make_field(None, None, 0.0, "not_found", ["Date could not be extracted safely."])

def parse_thai_date_to_iso(date_raw: Optional[str], time_raw: Optional[str]) -> Dict[str, Any]:
    if not date_raw or not time_raw:
        return make_field(None, None, 0.0, "not_available", ["Need both date and time to create ISO datetime guess."])

    date_norm = normalize_ocr_date_line(date_raw)
    time_match = re.search(r"([0-2]?\d)[:.](\d{2})", time_raw)
    if not time_match:
        return make_field(None, f"{date_raw} {time_raw}", 0.0, "parse_failed")

    slash_match = re.search(r"\b([0-3]?\d)[/-]([01]?\d)[/-](\d{2,4})\b", date_norm)
    month_match = re.search(r"\b([0-3]?\d)\s*([ก-๙A-Za-z\.]+)\s*(\d{2,4})\b", date_norm)

    if slash_match:
        day = int(slash_match.group(1))
        month = int(slash_match.group(2))
        year = int(slash_match.group(3))
    elif month_match:
        day = int(month_match.group(1))
        month_token = month_match.group(2).replace(" ", "").replace("ฯ", "")
        month_token = month_token.rstrip(".")
        year = int(month_match.group(3))
        month = THAI_MONTHS.get(month_token) or THAI_MONTHS.get(month_token.replace(".", ""))
        if month is None:
            if month_token.lower().startswith("n"):
                month = 2
            else:
                return make_field(None, f"{date_raw} {time_raw}", 0.0, "month_parse_failed")
    else:
        return make_field(None, f"{date_raw} {time_raw}", 0.0, "parse_failed")

    if year < 100:
        # Thai slips commonly use Buddhist short year, e.g. 65 -> 2565 -> 2022
        year = 2500 + year
    if year > 2400:
        year = year - 543

    hour = int(time_match.group(1))
    minute = int(time_match.group(2))

    try:
        dt = datetime(year, month, day, hour, minute)
        return make_field(dt.strftime("%Y-%m-%d %H:%M"), f"{date_raw} {time_raw}", 0.78, "thai_date_time_parse")
    except ValueError as e:
        return make_field(None, f"{date_raw} {time_raw}", 0.0, "datetime_value_error", [str(e)])


def is_account_line(line: str) -> bool:
    compact = line.replace(" ", "")
    has_mask = "x" in compact.lower()
    has_digit = bool(re.search(r"\d", compact))
    has_hyphen = "-" in compact
    if has_mask and has_digit:
        return True
    # Unmasked or partially masked bank-account-like pattern, conservative.
    if has_hyphen and len(re.sub(r"[^0-9xX-]", "", compact)) >= 8:
        return True
    return False


def normalize_account(line: str) -> str:
    value = line.strip()
    value = re.sub(r"\s*[-–]\s*", "-", value)
    value = re.sub(r"\s+", "-", value)
    return value


def detect_bank_line(line: str) -> Optional[str]:
    config = load_bank_config()
    low = line.lower().strip()

    # Person names can contain bank words in demo data, e.g. "นายกสิกร รักไทย".
    # Do not treat name-like lines as bank lines unless they explicitly contain bank markers.
    if re.match(r"^(นาย|นาง|น.ส|นางสาว)\s*", line.strip()) and "ธ." not in line:
        return None

    explicit_bank_markers = ["ธ.", "ธนาคาร", "bank", "krungthai", "k+", "scb", "กรุงไทย", "ไทยพาณิชย์"]

    for bank in config.get("banks", []):
        for kw in bank.get("keywords", []):
            kw_low = kw.lower()
            if kw_low in low:
                if any(marker in low for marker in explicit_bank_markers):
                    return bank.get("display_name")
                # Allow exact short bank line without person/title words.
                if low == kw_low or low in ["กสิกรไทย", "กรุงไทย", "ไทยพาณิชย์"]:
                    return bank.get("display_name")
    return None


def looks_like_name_line(line: str) -> bool:
    if not line:
        return False
    if re.search(r"\b[0-2]?\d[:.]\d{2}\b", line):
        return False
    if re.search(r"\d{1,2}\s*[ก-๙A-Za-z\.]+\s*\d{2,4}", line):
        return False
    if any(k.lower() in line.lower() for k in STOP_NAME_KEYWORDS):
        return False
    if is_account_line(line):
        return False
    if detect_bank_line(line):
        return False
    if find_money_in_text(line):
        return False
    if re.search(r"\d{4,}", line):
        return False
    # Thai person names commonly have นาย/นาง/น.ส, but we also allow Thai text lines.
    if re.search(r"[ก-๙]", line):
        return True
    return False


def extract_party_groups(lines: List[str]) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    accounts = []
    warnings = []
    for i, line in enumerate(lines):
        if is_account_line(line):
            accounts.append((i, normalize_account(line)))

    groups = []
    for idx, account in accounts[:2]:
        bank_value = None
        bank_idx = None
        for j in range(idx - 1, max(-1, idx - 5), -1):
            bank = detect_bank_line(lines[j])
            if bank:
                bank_value = bank
                bank_idx = j
                break

        name_lines = []
        if bank_idx is not None:
            for j in range(bank_idx - 1, max(-1, bank_idx - 4), -1):
                if looks_like_name_line(lines[j]):
                    name_lines.insert(0, lines[j])
                elif name_lines:
                    break
        else:
            for j in range(idx - 1, max(-1, idx - 4), -1):
                if looks_like_name_line(lines[j]):
                    name_lines.insert(0, lines[j])
                elif name_lines:
                    break

        groups.append({
            "name": " ".join(name_lines).strip() if name_lines else None,
            "bank": bank_value,
            "account": account,
            "account_line_index": idx,
        })

    if len(groups) < 2:
        warnings.append("Could not confidently find two account groups for sender and receiver.")

    sender = groups[0] if len(groups) >= 1 else {}
    receiver = groups[1] if len(groups) >= 2 else {}
    return sender, receiver, warnings


def extract_from_full_text(full_text: str, raw_items: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    lines = split_lines(full_text)
    warnings = []

    bank_field, bank_candidates = detect_bank_or_app(lines)
    format_field = guess_slip_format(lines)
    status_field = extract_transfer_status(lines)
    reference_field = extract_reference_id(lines)
    amount_field = extract_amount(lines)
    fee_field = extract_fee(lines)
    date_field = extract_date(lines)
    time_field = extract_time(lines)
    datetime_field = parse_thai_date_to_iso(date_field.get("value"), time_field.get("value"))

    sender, receiver, party_warnings = extract_party_groups(lines)
    warnings.extend(party_warnings)

    fields = {
        "transfer_status": status_field,
        "slip_format_guess": format_field,
        "source_app_or_bank": bank_field,
        "reference_id": reference_field,
        "amount": amount_field,
        "fee": fee_field,
        "transaction_date_raw": date_field,
        "transaction_time_raw": time_field,
        "transaction_datetime_iso_guess": datetime_field,
        "sender_name": make_field(sender.get("name"), sender.get("name"), 0.55 if sender.get("name") else 0.0, "account_group_heuristic"),
        "sender_bank": make_field(sender.get("bank"), sender.get("bank"), 0.70 if sender.get("bank") else 0.0, "account_group_heuristic"),
        "sender_account": make_field(sender.get("account"), sender.get("account"), 0.82 if sender.get("account") else 0.0, "account_pattern"),
        "receiver_name": make_field(receiver.get("name"), receiver.get("name"), 0.55 if receiver.get("name") else 0.0, "account_group_heuristic"),
        "receiver_bank": make_field(receiver.get("bank"), receiver.get("bank"), 0.70 if receiver.get("bank") else 0.0, "account_group_heuristic"),
        "receiver_account": make_field(receiver.get("account"), receiver.get("account"), 0.82 if receiver.get("account") else 0.0, "account_pattern"),
    }

    missing = [name for name in FIELD_NAMES if fields.get(name, {}).get("value") in [None, ""]]
    low_confidence = [
        name for name, field in fields.items()
        if field.get("value") not in [None, ""] and field.get("confidence", 0) < 0.60
    ]

    extraction_status = "success"
    if missing:
        extraction_status = "partial_success"
    if len(missing) >= len(FIELD_NAMES) - 3:
        extraction_status = "raw_ocr_fallback"
        warnings.append("Most fields could not be extracted; raw OCR text is the main fallback.")

    # Add field-specific warnings to top-level warnings for quick report.
    for name, field in fields.items():
        for w in field.get("warnings", []):
            warnings.append(f"{name}: {w}")

    return {
        "status": extraction_status,
        "document_type": "bank_transfer_slip_demo",
        "detected_bank_candidates": bank_candidates,
        "fields": fields,
        "missing_fields": missing,
        "low_confidence_fields": low_confidence,
        "warnings": warnings,
        "line_count": len(lines),
        "normalized_lines": lines,
        "raw_full_text": full_text,
    }
