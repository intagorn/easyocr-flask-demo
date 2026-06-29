# Template Folder Exporter

This tool exports templates from MySQL into image + JSON pairs that can be re-imported later.

It is the companion tool for:

```text
tools/import_templates_from_folder.py
```

## Export all templates

```bash
python tools/export_templates_to_folder.py exported_templates --overwrite
```

Output:

```text
exported_templates/
  ktb-2026-01.jpg
  ktb-2026-01.json
  kbank-2026-01.jpg
  kbank-2026-01.json
```

## Export one template

```bash
python tools/export_templates_to_folder.py exported_templates --template-code ktb-2026-01 --overwrite
```

## Export only active templates

```bash
python tools/export_templates_to_folder.py exported_templates --active-only --overwrite
```

## Save report

```bash
python tools/export_templates_to_folder.py exported_templates --overwrite --report export_report.json
```

## Re-import later

```bash
python tools/import_templates_from_folder.py exported_templates --replace-existing --created-by admin
```

## Notes

- The exporter uses the first `create_sample` image if available.
- If no `create_sample` exists, it uses the first sample image.
- JSON output uses the same structure as the importer.
- Box coordinates are normalized `[x1, y1, x2, y2]`.
