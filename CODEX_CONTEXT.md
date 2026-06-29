# CODEX_CONTEXT.md

## Project summary

This repository is a Flask + EasyOCR demo for Thai bank-transfer slip OCR.

The MVP extracts fields from Thai transfer-slip screenshots using:

1. EasyOCR on the full image.
2. A shared Generic Rules parser.
3. Optional QR detection as supporting information.
4. File-based batch jobs for ZIP uploads.

Main design decision:

> Generic Rules OCR is the main extraction engine. QR extraction and any future LLM/template layer should be support/fallback/verification only.

The current MVP intentionally avoids a database.

---

## Current important routes

Single image Generic Rules OCR:

```text
/generic-rules-ocr
```

Batch ZIP Generic Rules OCR:

```text
/batch-generic-rules-ocr
```

Jobs UI:

```text
/jobs
/jobs/<job_id>
/jobs/<job_id>/results
/jobs/<job_id>/download
/jobs/<job_id>/summary.json
/jobs/<job_id>/json/<output_stem>.json
/jobs/<job_id>/images/<output_stem>
```

API:

```text
POST /api/batch-jobs
GET  /api/batch-jobs
GET  /api/batch-jobs/<job_id>
GET  /api/batch-jobs/<job_id>/summary.json
GET  /api/batch-jobs/<job_id>/download
POST /api/batch-jobs/reset-active
```

---

## Important files

```text
app/services/generic_rule_ocr_service.py   # shared rule parser
app/services/ocr_service.py                # EasyOCR wrapper
app/services/batch_job_service.py          # file-based batch job service
tools/process_zip_generic_rules.py         # CLI ZIP processor
app/routes/web_routes.py                   # web pages
app/routes/api_routes.py                   # API
```

Important templates:

```text
app/templates/generic_rules_ocr.html
app/templates/batch_generic_rules_ocr.html
app/templates/jobs.html
app/templates/job_detail.html
app/templates/job_results.html
```

---

## Batch job architecture

Batch jobs are file-based under:

```text
storage/jobs/<job_id>/
```

Each job folder may contain:

```text
job_status.json
input.zip
result.zip
summary.csv
summary.json
json/
raw_text/
errors/
work/
```

Status values:

```text
queued
processing
finished
failed
cancelled
```

Current design:

- No database.
- Maximum active jobs = queued + processing.
- Only one background worker processes queued jobs at a time.
- The worker starts inside the Flask/Gunicorn process unless disabled by environment variable.

Environment variables:

```text
EASYOCR_MAX_ACTIVE_JOBS=10
EASYOCR_JOB_WORKER_SLEEP_SECONDS=3
EASYOCR_DISABLE_JOB_WORKER=0
EASYOCR_MAX_CONTENT_MB=300
```

---

## Known production issue

Current batch worker runs inside the Gunicorn web process. This can cause trouble on large ZIP batches.

Observed server issue:

- A user uploaded 30 images.
- Batch processing stuck around 6/30.
- Gunicorn logs showed repeated:

```text
CRITICAL WORKER TIMEOUT
Worker was sent SIGKILL! Perhaps out of memory?
```

Temporary server fix:

```text
gunicorn -w 1 --timeout 900 --graceful-timeout 60 -b 0.0.0.0:5000 wsgi:app
```

Better future fix:

> Move the batch OCR worker into a separate worker process/systemd service outside Gunicorn.

Suggested first Codex task:

1. Add better progress/debug logging.
2. Store current filename and index in `job_status.json` before each image.
3. Store per-image start/end timestamps.
4. Mark stale `processing` jobs as failed on startup.
5. Do not add a database yet.
6. Keep existing UI/API behavior.

Suggested later Codex task:

> Split batch processing into a separate systemd worker service while keeping file-based job folders.

---

## Deployment context

Server path used during testing:

```text
/root/easyocr_flask_demo
```

Systemd service name:

```text
easyocr-demo
```

Recommended ExecStart for current MVP:

```text
/root/easyocr_flask_demo/venv/bin/gunicorn -w 1 --timeout 900 --graceful-timeout 60 -b 0.0.0.0:5000 wsgi:app
```

Keep `-w 1` for now because EasyOCR can use high memory and the file-based in-process worker was designed for one worker process.

---

## Main extraction philosophy

Rules should be conservative.

High-risk fields:

```text
amount
transaction date/time
reference_id
receiver account
transfer status
```

Medium-risk fields:

```text
sender_name
receiver_name
sender_bank
receiver_bank
```

Low-priority field:

```text
note
```

LLMs, if added later, should not replace rules. They should only:

- Fill missing fields.
- Suggest low-confidence corrections.
- Explain/normalize names/notes.
- Return JSON only.
- Be validated by code before use.

Recommended future LLM flow:

```text
EasyOCR
-> Generic Rules parser
-> Optional local LLM only for missing/low-confidence fields
-> Schema validation
-> Human review when uncertain
```

---

## Rule updates already implemented

### PromptPay

PromptPay is treated as bank/channel keyword.

### Account group sequence fallback

For slips without explicit `จาก` / `ไปยัง`, repeated account groups are used:

```text
name
bank
account

name
bank
account
```

or:

```text
name
account
bank

name
account
bank
```

### Thai date corrections

Known OCR month corrections include:

```text
n.พ. -> ก.พ.
๓.ค. -> ต.ค.
5.ค. -> ธ.ค.
```

`5.ค.` is only used inside the date parser.

### Amount correction

If OCR attaches extra decimal digits:

```text
100,000.00748
```

Normalize to:

```text
100000.00
```

Do not round to 100000.01. Extra digits are treated as OCR noise and trimmed.

### TTB amount fallback

Some TTB slips show amount after success/date without `จำนวนเงิน`.

Example:

```text
โอนเงินสำเร็จ
10 ธ.ค. 67 09:41
10,000.00
ค่าธรรมเนียม
```

Use top-position fallback but add warning.

### Reference label variants

Support:

```text
reference no:
reference n0:
ref no:
ref n0:
รหัสอ้างอิง
เลขที่อ้างอิง
เลขที่รายการ
```

### Account cleanup

Examples:

```text
000-1-23456=7 -> 000-1-23456-7
|888-8-8888-8| -> 888-8-8888-8
ixxx-x-x8888-x -> xxx-x-x8888-x
```

Allowed account characters after cleanup:

```text
digits 0-9
x / X
dash -
spaces before normalization
equals as dash only in safe contexts
```

### Transaction time priority

Prefer transaction time attached to a Thai date.

Example raw OCR:

```text
|9:41
ทำรายการสำเร็จ
โอนเงินสำเร็จ
26 ม.ค. 65 05:10 น.
```

Expected transaction time:

```text
05:10
```

The earlier `9:41` is likely phone status-bar/screenshot time.

### Balance exclusion

Do not use `ยอดเงินคงเหลือ` / balance / remaining balance as transfer amount.

Example:

```text
จำนวน:
|888.00 บาท
ค่าธรรมเนียม:
|o.00 บาท
ยอดเงินคงเหลือ: 83,888.00 บาท
```

Expected:

```text
amount: 888.00
fee: 0.00
```

---

## Known limitations

- OCR quality strongly affects extraction.
- Some slips with decorative backgrounds or cropped screenshots cause OCR merging/noise.
- Batch processing inside Gunicorn is fragile for large batches.
- No authentication yet.
- No database yet.
- QR extraction is support/fallback, not the main engine.
- Human review is expected for uncertain fields.

---

## Guidance for Codex

When modifying this project:

1. Avoid large rewrites.
2. Preserve no-database design unless explicitly requested.
3. Keep single-image and batch routes using the same Generic Rules parser.
4. Do not let new rules break already-good cases.
5. Add warnings when using fallback or OCR correction.
6. Prefer small, testable changes.
7. Keep deployment simple for Ubuntu systemd + Gunicorn.
8. Be careful with EasyOCR memory usage.
9. Do not commit sample bank slips or private customer data.
10. Update this file if architecture changes.
