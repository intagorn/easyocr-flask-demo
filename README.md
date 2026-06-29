# EasyOCR Flask Demo - v13.4 Template Folder Importer Anchor Type Fix

This version keeps all v11 pages and adds a standalone developer/admin tool:

- `tools/import_templates_from_folder.py`

## New tool

Import a folder containing image files and same-name JSON template definitions.

Example:

```text
examples/template_import/
  ktb-2026-01.jpg
  ktb-2026-01.json
  kbank-2026-01.jpg
  kbank-2026-01.json
```

Run dry-run first:

```bash
python tools/import_templates_from_folder.py examples/template_import --dry-run
```

Then import:

```bash
python tools/import_templates_from_folder.py examples/template_import --created-by admin
```

Replace existing templates with same `template_code`:

```bash
python tools/import_templates_from_folder.py examples/template_import --replace-existing --created-by admin
```

## Filename as identifier

If `template_code` is not provided in the JSON, the image filename stem is used.

Example:

```text
ktb-2026-01.jpg -> template_code = ktb-2026-01
```

## Existing pages

- `/ocr`
- `/hybrid-ocr`
- `/zone-ocr`
- `/template-ocr`
- `/templates`
- `/templates/new`
- `/templates/<template_id>`

## Important design note

Zone OCR can be worse than pure generic OCR if the zone is wrong. Therefore, the current strategy should stay conservative:

```text
generic extraction = primary
template zone = confirm/rescue only
bad or mismatched zone should not override strong generic extraction
```

## Default database name

- `DB_NAME=easyocr_slip_demo`

## Setup

```bash
pip install -r requirements.txt
python app.py
```

See:

```text
tools/README_template_importer.md
```


## v13.4 fix

The importer now inserts `template_samples.sample_type` as `imported` instead of the too-long value `imported_template_sample`.


## v13.4 schema fix

The importer now matches the provided `template_fields` schema:

- uses `postprocess_rules_json`
- uses `validation_rules_json`
- uses `fallback_rules_json`
- no longer uses the old non-existent `validation_regex` column
- no longer uses the old non-existent `postprocess_rule_json` column
- uses `template_samples.sample_type = 'create_sample'`


## v13.4 anchor_type fix

The importer now maps friendly JSON anchor types to your DB ENUM:

- `text` / `label` -> `text_label`
- `logo` / `logo_or_text` -> `logo_area`
- success anchors -> `success_text`
- QR anchors -> `key_area`
- unknown types -> `other`

Your DB ENUM is:

```sql
ENUM('key_area', 'logo_area', 'text_label', 'success_text', 'other')
```


## v13.4 box editing

Template detail page now supports visual editing of saved boxes:

- Turn on `Edit saved boxes`
- Click an existing anchor/field box
- Drag inside the box to move it
- Drag square handles to resize it
- Click `Save Edited Box` to update MySQL

Added API endpoints:

- `PATCH /api/templates/<template_id>/fields/<field_id>/box`
- `PATCH /api/templates/<template_id>/anchors/<anchor_id>/box`


## v13.4 box edit fix

Fixed saved-box editing:

- existing saved boxes now receive mouse events when `Edit saved boxes` is enabled
- clicking an existing box no longer starts drawing a new red box
- draw-new-box mode is paused while edit mode is enabled


## v13.4 box save fix

Fixed `Error: Field not found or unchanged.` when saving edited boxes.

MySQL/PyMySQL can return `0` affected rows for an UPDATE when the stored FLOAT values are considered unchanged or rounded. The API now treats the save request as successful as long as the request is valid.


## v13.4 template exporter

Added standalone exporter:

```text
tools/export_templates_to_folder.py
```

Export all templates from MySQL into image + JSON pairs:

```bash
python tools/export_templates_to_folder.py exported_templates --overwrite
```

Then re-import later:

```bash
python tools/import_templates_from_folder.py exported_templates --replace-existing --created-by admin
```

This makes template backup, transfer, and re-testing easier.

### About editing multiple boxes

Current UI intentionally saves one edited box at a time. Multiple-box batch save is not implemented yet. For now, edit one box, save, then edit the next box.


## v13.4 generic rules OCR

Added a new page with no database and no template dependency:

```text
/generic-rules-ocr
```

Pipeline:

```text
1. Run EasyOCR once on the full image
2. Parse raw OCR full text with generic bank-transfer rules
3. Treat พร้อมเพย์ / PromptPay as a bank_or_channel keyword inside sender/receiver sections
4. Decode QR if possible
5. Show image preview with evidence boxes
6. Show raw OCR text, extracted fields, QR result, and full JSON
```

This page is intended to be the main rule-testing page. It is easier to iterate rules from raw OCR text than maintaining many templates in the first version.

Current limitation:

```text
Rule-based extraction can conflict with OCR errors or unusual slip layouts. The result should be treated as a pre-fill result for human review, not as guaranteed truth.
```


## v13.4 account group sequence fallback

Added a fallback rule for slips without explicit `จาก` / `ไปยัง` labels.

Expected OCR pattern:

```text
person name
bank name
account

person name
bank name
account
```

The first group is treated as sender and the second group as receiver.

This helps K PLUS-style OCR such as:

```text
นายกสิกร รักไทย
ธ.กสิกรไทย
xxx-x-x8888-x
นายกสิกร รักไทย
ธ.กสิกรไทย
888-8-8888-8
```

Expected extraction:

```text
sender_name = นายกสิกร รักไทย
sender_bank = Kasikornbank / K PLUS / ธนาคารกสิกรไทย
sender_account = xxx-x-x8888-x
receiver_name = นายกสิกร รักไทย
receiver_bank = Kasikornbank / K PLUS / ธนาคารกสิกรไทย
receiver_account = 888-8-8888-8
```

Important: this is a fallback rule. It is used mainly when sender/receiver section labels are missing or incomplete.


## v13.4 name date/time cleanup

Added safer name extraction for account-group fallback.

Fixes cases where date/time is accidentally included in sender/receiver names:

```text
29 พ.ค. 66
11:00 น.
นาย ปฏิญญา ม
ธ.กสิกรไทย
xxx-x-x6745-x
```

Expected:

```text
sender_name = นาย ปฏิญญา ม
```

Also handles OCR-merged lines such as:

```text
29 พ.ค. 66 11:00 น. นาย ปฏิญญา ม
```

by stripping the date/time prefix and keeping only:

```text
นาย ปฏิญญา ม
```

Rules added:

- reject pure Thai date lines as names
- reject pure time lines as names
- strip date/time prefix before Thai title words such as นาย / นาง / นางสาว / น.ส.
- stop account-group name search when it reaches definite date/time or app-marker lines


## v13.4 Thai date OCR correction

Added Thai date OCR correction for cases such as:

```text
01 n.พ. 2565
```

Expected interpretation:

```text
01 ก.พ. 2565
```

New behavior:

```text
transaction_date_raw = 01 ก.พ. 2565
transaction_datetime_iso_guess = 2022-02-01T15:40
```

Rules added:

- accept month-like OCR token containing Thai/Latin characters and dots
- map known OCR February variants such as `n.พ.`, `n.พ`, and `nพ` to `ก.พ.`
- treat four-digit Buddhist years `2540–2599` as strong date evidence
- convert Buddhist year to Gregorian year by subtracting 543
- keep warnings when date/month was OCR-corrected

This is still a rule-based correction and should be reviewed when OCR is noisy.


## v13.4 low-priority note extraction

Added strict, low-priority extraction for `note`.

Supported examples:

```text
บันทึกช่วยจำ
ชาญ
```

Expected:

```text
note = ชาญ
```

Also supports same-line note:

```text
บันทึกช่วยจำ: สมัครสมาชิก นายทศณรงค์ เป้ามัจฉา
```

Important design:

- note extraction only runs when a clear note label exists, such as `บันทึกช่วยจำ`, `หมายเหตุ`, `note`, or `memo`
- it stops before QR/instruction text such as `ผู้รับเงินสามารถสแกน...` or `ตรวจสอบสถานะ...`
- it is intentionally low priority and should not affect amount/date/name extraction
- the note field includes a warning because OCR note text is often noisy and should be reviewed

## v16.3 CLI batch ZIP processor

Added a standalone command-line batch processor for Generic Rules OCR.

This tool does **not** use MySQL, template manager, template zones, or the database. It uses the current `/generic-rules-ocr` extraction pipeline for each image.

### Command

Run from the project root:

```bash
python tools/process_zip_generic_rules.py input_slips.zip output_results.zip
```

Example:

```bash
cd /root/easyocr_flask_demo
source venv/bin/activate
python tools/process_zip_generic_rules.py /root/input_slips.zip /root/output_results.zip
```

### Input

The input is a ZIP file containing images.

Allowed image extensions:

```text
.jpg
.jpeg
.png
.webp
```

Non-image files are skipped. Unsafe ZIP paths such as `../../etc/passwd` are rejected.

### Output ZIP structure

The output ZIP contains:

```text
output_results.zip
  summary.csv
  summary.json
  json/
    slip001.json
    slip002.json
  raw_text/
    slip001.txt
    slip002.txt
  errors/
    failed_slip.json
```

For each image, the tool creates:

```text
json/<same_image_stem>.json
raw_text/<same_image_stem>.txt
```

If an image fails, the error is saved as:

```text
errors/<same_image_stem>.json
```

### Summary files

`summary.csv` is intended for quick review in Excel.

Main columns include:

```text
filename
status
amount
fee
reference_id
transaction_date_raw
transaction_time_raw
transaction_datetime_iso_guess
transfer_status
source_app_or_bank
sender_name
sender_bank
sender_account
receiver_name
receiver_bank
receiver_account
note
missing_fields
low_confidence_fields
warnings
json_file
raw_text_file
error_file
```

`summary.json` contains the same batch-level information plus skipped file records.

### Useful options

Limit the number of images:

```bash
python tools/process_zip_generic_rules.py input_slips.zip output_results.zip --max-images 100
```

Limit total extracted image size:

```bash
python tools/process_zip_generic_rules.py input_slips.zip output_results.zip --max-total-extracted-mb 300
```

Keep the working folder for debugging:

```bash
python tools/process_zip_generic_rules.py input_slips.zip output_results.zip --keep-work
```

Use a specific working folder:

```bash
python tools/process_zip_generic_rules.py input_slips.zip output_results.zip --work-dir storage/tmp_batch_test
```

### Notes

- Images are processed one by one to reduce memory risk.
- EasyOCR model loading can take time on the first image.
- Field confidence values are heuristic rule confidence, not EasyOCR character confidence.
- This is the foundation for the later upload-page/job-queue system.


## v16.3 CLI batch ZipInfo fix

Fixed the CLI batch processor on Python versions where `zipfile.ZipInfo` does not allow custom attributes.

Previous error:

```text
AttributeError: 'ZipInfo' object has no attribute '_safe_name'
```

The batch tool now stores safe ZIP member metadata in a dictionary instead of attaching attributes to `ZipInfo`.

Run:

```bash
python tools/process_zip_generic_rules.py input_slips.zip output_results.zip
```


## v16.3 Thai October OCR correction

Added a known OCR correction for October:

```text
16 ๓.ค. 2568
```

Expected correction:

```text
16 ต.ค. 2568
```

This handles cases where OCR reads `ต` in `ต.ค.` as Thai digit `๓`.

Aliases added:

```text
๓.ค. / ๓.ค / ๓ค -> ต.ค.
```

This is limited to the month-token parser, so it should not affect money, reference ID, account, or name extraction.


## v16.3 file-based batch job system

Added a no-database job system for batch Generic Rules OCR.

### Job storage

Jobs are stored as folders:

```text
storage/jobs/<job_id>/
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

Each job has `job_status.json`.

Supported statuses:

```text
queued
processing
finished
failed
cancelled
```

### Queue rules

```text
Maximum active jobs = queued + processing = 10
Only one job processes at a time
If active jobs >= 10, new submissions are rejected
```

This is intentional because EasyOCR can use a lot of memory.

Environment variables:

```text
EASYOCR_MAX_ACTIVE_JOBS=10
EASYOCR_JOB_WORKER_SLEEP_SECONDS=3
EASYOCR_DISABLE_JOB_WORKER=0
EASYOCR_MAX_CONTENT_MB=300
```

### API endpoints

Create batch job:

```bash
curl -X POST http://127.0.0.1:5000/api/batch-jobs \
  -F "zip_file=@input_slips.zip"
```

Expected response:

```json
{
  "status": "queued",
  "job_id": "20260625_153012_abcd1234",
  "status_url": "/api/batch-jobs/20260625_153012_abcd1234",
  "download_url": "/api/batch-jobs/20260625_153012_abcd1234/download",
  "summary_json_url": "/api/batch-jobs/20260625_153012_abcd1234/summary.json"
}
```

List jobs:

```bash
curl http://127.0.0.1:5000/api/batch-jobs
```

Check one job:

```bash
curl http://127.0.0.1:5000/api/batch-jobs/<job_id>
```

Download result ZIP after the job is finished:

```bash
curl -L -o result.zip http://127.0.0.1:5000/api/batch-jobs/<job_id>/download
```

Download summary JSON after the job is finished:

```bash
curl -L -o summary.json http://127.0.0.1:5000/api/batch-jobs/<job_id>/summary.json
```

### Notes

- This batch job system uses Generic Rules OCR only.
- It does not use MySQL, templates, or zone OCR.
- The worker is started automatically when Flask starts.
- This MVP assumes one Gunicorn worker process. If Gunicorn workers are increased later, move the worker to a separate process or use Redis/Celery/RQ.
- Step 5–8 can add UI pages for upload/status/result table later.


## v16.3 batch job UI and result table

Added web UI pages for the no-database batch Generic Rules OCR job system.

### UI pages

Upload ZIP:

```text
/batch-generic-rules-ocr
```

List recent jobs:

```text
/jobs
```

View job status/progress:

```text
/jobs/<job_id>
```

View result table:

```text
/jobs/<job_id>/results
```

Download result ZIP:

```text
/jobs/<job_id>/download
```

View summary JSON:

```text
/jobs/<job_id>/summary.json
```

View per-image JSON:

```text
/jobs/<job_id>/json/<output_stem>.json
```

View input image preview:

```text
/jobs/<job_id>/images/<output_stem>
```

### Result table columns

```text
thumbnail
filename
status
amount
transaction date/time
reference_id
sender_name
receiver_name
receiver_account
warnings
link to per-image JSON
```

### API endpoints

The API endpoints from v15 are still available:

```text
POST /api/batch-jobs
GET  /api/batch-jobs
GET  /api/batch-jobs/<job_id>
GET  /api/batch-jobs/<job_id>/summary.json
GET  /api/batch-jobs/<job_id>/download
```

### Notes

- No database is used.
- Job metadata is stored in `storage/jobs/<job_id>/job_status.json`.
- The UI result table reads from `summary.json`.
- The image preview uses the safely extracted input image from the job work folder.


## v16.3 reset active jobs

Added a simple reset feature for stuck queued/processing jobs.

### UI

Open:

```text
/jobs
```

Then click:

```text
Reset queued/processing jobs
```

This marks all jobs with status `queued` or `processing` as:

```text
cancelled
```

It does not delete finished result files.

### API

```bash
curl.exe -X POST http://127.0.0.1:5000/api/batch-jobs/reset-active
```

### Manual emergency cleanup

If the worker is stuck inside EasyOCR, stop the service first:

```bash
sudo systemctl stop easyocr-demo
```

Then either reset via UI/API after restarting, or delete all job folders:

```bash
rm -rf /root/easyocr_flask_demo/storage/jobs/*
```

Then restart:

```bash
sudo systemctl start easyocr-demo
```

If using a custom storage root, check:

```bash
echo $EASYOCR_STORAGE_ROOT
```

The default storage folder is:

```text
/root/easyocr_flask_demo/storage/jobs/
```


## v16.3 Bangkok Bank and TTB rule fixes

Updated the shared Generic Rules OCR parser used by both:

```text
/generic-rules-ocr
/batch-generic-rules-ocr
```

Both pages call the same `run_generic_rule_ocr()` / `extract_generic_rules_from_full_text()` rule code, so these fixes apply to single-image OCR and batch ZIP jobs.

### Added/updated rules

- Added Bangkok Bank keyword detection.
- Added TTB keyword detection.
- Added receiver section label variant: `ไปที่`.
- Added account support for unmasked 10–13 digit account numbers.
- Added account cleanup: `000-1-23456=7` -> `000-1-23456-7`.
- Added English receiver-name support, e.g. `srithanya`.
- Added amount cleanup for OCR-noisy decimals:
  - `100,000.00748` -> `100000.00`
  - extra decimal digits are trimmed, not rounded.
- Added top-position amount fallback for slips without `จำนวนเงิน` label, e.g. TTB:
  - success line
  - date/time line
  - amount line
- Added Thai month OCR correction:
  - `5.ค.` -> `ธ.ค.`
- Added reference label variant:
  - `reference n0:` / `ref n0:` -> `reference no:`


## v16.3 transaction time, account cleanup, and balance exclusion

Updated the shared Generic Rules OCR parser used by both:

```text
/generic-rules-ocr
/batch-generic-rules-ocr
```

### Added/updated rules

- Transaction time priority:
  - Prefer time on the same line as Thai transaction date.
  - Prefer time immediately after a Thai date line.
  - Ignore earlier standalone time before transfer status as likely phone screenshot/status-bar time.
- Account cleanup:
  - `|888-8-8888-8|` -> `888-8-8888-8`
  - `ixxx-x-x8888-x` -> `xxx-x-x8888-x`
  - Keeps account characters limited to digits, x/X, dash, equals-as-dash, and spaces before normalization.
- Amount/balance safety:
  - `ยอดเงินคงเหลือ` / balance / remaining balance is excluded from transfer amount extraction.
  - Amount after `จำนวน:` still works even if OCR adds a leading border such as `|888.00 บาท`.
- Tested with K PLUS raw OCR containing phone screenshot time `|9:41` and transaction datetime `26 ม.ค. 65 05:10 น.`.


## GitHub / Codex handoff

This version includes two handoff documents:

```text
CODEX_CONTEXT.md
GITHUB_UPLOAD_WINDOWS.md
```

Read `CODEX_CONTEXT.md` before asking Codex to modify the project. It summarizes the current architecture, known issues, rule decisions, and recommended first Codex tasks.

Read `GITHUB_UPLOAD_WINDOWS.md` for step-by-step instructions to upload this project to GitHub from Windows.

Recommended first Codex task:

```text
Add better batch job progress/debug logging and stale-job handling without adding a database.
```
