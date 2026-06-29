# Template Folder Importer

This tool imports same-name image + JSON template files into the MySQL template tables and copies the image into storage.

## Folder format

```text
template/
  ktb-2026-01.jpg
  ktb-2026-01.json

  kbank-2026-01.jpg
  kbank-2026-01.json
```

The filename stem is used as the default `template_code`.

Example:

```text
ktb-2026-01.jpg -> template_code = ktb-2026-01
```

## Run

From project root:

```bash
python tools/import_templates_from_folder.py examples/template_import --dry-run
```

If the dry run is OK:

```bash
python tools/import_templates_from_folder.py examples/template_import --created-by admin
```

If you want to replace existing templates with the same `template_code`:

```bash
python tools/import_templates_from_folder.py examples/template_import --replace-existing --created-by admin
```

Save a JSON report:

```bash
python tools/import_templates_from_folder.py examples/template_import --dry-run --report import_report.json
```

## JSON schema

```json
{
  "bank_code": "krungthai",
  "template_name": "Krungthai transfer slip layout 2026 example",
  "version_label": "v1",
  "status": "draft",
  "description": "optional",
  "optional_keywords": ["Krungthai", "กรุงไทย", "โอนเงินสำเร็จ"],
  "anchors": [
    {
      "anchor_name": "success_text",
      "anchor_type": "text",
      "expected_keywords": ["โอนเงินสำเร็จ"],
      "required": true,
      "weight": 1.5,
      "box": [0.15, 0.15, 0.60, 0.23]
    }
  ],
  "fields": [
    {
      "field_name": "reference_id",
      "display_name": "รหัสอ้างอิง",
      "field_type": "text",
      "required": true,
      "crop_margin": 0.01,
      "box": [0.30, 0.23, 0.82, 0.28]
    }
  ]
}
```

Box format:

```text
[x1, y1, x2, y2]
```

All values are normalized from `0.0` to `1.0`.

## Notes

The included example JSONs are approximate. Use the Template Manager page to adjust boxes after importing if needed.


## v12.3 fix

The importer now inserts `template_samples.sample_type` as `imported` instead of the too-long value `imported_template_sample`.


## v12.3 schema fix

The importer now matches the provided `template_fields` schema:

- uses `postprocess_rules_json`
- uses `validation_rules_json`
- uses `fallback_rules_json`
- no longer uses the old non-existent `validation_regex` column
- no longer uses the old non-existent `postprocess_rule_json` column
- uses `template_samples.sample_type = 'create_sample'`


## v12.3 anchor_type fix

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
