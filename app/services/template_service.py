from app.services.db_service import fetch_all, fetch_one, execute_insert, execute_sql


def _format_datetime_rows(rows, keys=("updated_at", "created_at", "tested_at")):
    for row in rows:
        for key in keys:
            value = row.get(key)
            if value is not None and hasattr(value, "strftime"):
                row[key] = value.strftime("%Y-%m-%d %H:%M:%S")
    return rows


def _format_datetime_row(row, keys=("updated_at", "created_at", "tested_at")):
    if not row:
        return row
    for key in keys:
        value = row.get(key)
        if value is not None and hasattr(value, "strftime"):
            row[key] = value.strftime("%Y-%m-%d %H:%M:%S")
    return row


def get_banks_with_template_counts():
    sql = """
        SELECT
            b.id,
            b.bank_code,
            b.bank_name_th,
            b.bank_name_en,
            b.is_active,
            COUNT(t.id) AS template_count
        FROM banks b
        LEFT JOIN templates t ON t.bank_id = b.id
        GROUP BY b.id, b.bank_code, b.bank_name_th, b.bank_name_en, b.is_active
        ORDER BY b.bank_name_th ASC
    """
    return fetch_all(sql)


def get_banks():
    sql = """
        SELECT id, bank_code, bank_name_th, bank_name_en, is_active
        FROM banks
        ORDER BY bank_name_th ASC
    """
    return fetch_all(sql)


def get_templates():
    sql = """
        SELECT
            t.id,
            t.template_code,
            t.template_name,
            t.version_label,
            t.status,
            t.expected_aspect_ratio,
            t.updated_at AS updated_at,
            b.bank_code,
            b.bank_name_th,
            COUNT(DISTINCT tf.id) AS field_count,
            COUNT(DISTINCT ts.id) AS sample_count
        FROM templates t
        JOIN banks b ON b.id = t.bank_id
        LEFT JOIN template_fields tf ON tf.template_id = t.id AND tf.is_active = TRUE
        LEFT JOIN template_samples ts ON ts.template_id = t.id
        GROUP BY
            t.id,
            t.template_code,
            t.template_name,
            t.version_label,
            t.status,
            t.expected_aspect_ratio,
            t.updated_at,
            b.bank_code,
            b.bank_name_th
        ORDER BY t.updated_at DESC, t.id DESC
    """
    return _format_datetime_rows(fetch_all(sql))


def get_template_by_code(template_code: str):
    sql = """
        SELECT id, template_code, template_name
        FROM templates
        WHERE template_code = %s
        LIMIT 1
    """
    return fetch_one(sql, (template_code,))


def get_template_detail(template_id: int):
    sql = """
        SELECT
            t.id,
            t.bank_id,
            t.template_code,
            t.template_name,
            t.version_label,
            t.status,
            t.expected_width,
            t.expected_height,
            t.expected_aspect_ratio,
            t.description,
            t.notes,
            t.optional_keywords_json,
            t.template_config_json,
            t.created_by,
            t.created_at,
            t.updated_at,
            b.bank_code,
            b.bank_name_th,
            b.bank_name_en
        FROM templates t
        JOIN banks b ON b.id = t.bank_id
        WHERE t.id = %s
        LIMIT 1
    """
    return _format_datetime_row(fetch_one(sql, (template_id,)))


def get_template_samples(template_id: int):
    sql = """
        SELECT
            id,
            template_id,
            sample_name,
            image_path,
            image_width,
            image_height,
            aspect_ratio,
            sample_type,
            notes,
            uploaded_by,
            created_at
        FROM template_samples
        WHERE template_id = %s
        ORDER BY created_at ASC, id ASC
    """
    return _format_datetime_rows(fetch_all(sql, (template_id,)))


def get_template_fields(template_id: int):
    sql = """
        SELECT
            id,
            template_id,
            field_name,
            display_name,
            field_type,
            x1,
            y1,
            x2,
            y2,
            required,
            crop_margin,
            sort_order,
            postprocess_rules_json,
            validation_rules_json,
            fallback_rules_json,
            is_active,
            created_at,
            updated_at
        FROM template_fields
        WHERE template_id = %s
        ORDER BY sort_order ASC, id ASC
    """
    return _format_datetime_rows(fetch_all(sql, (template_id,)))


def get_template_anchors(template_id: int):
    sql = """
        SELECT
            id,
            template_id,
            anchor_name,
            anchor_type,
            x1,
            y1,
            x2,
            y2,
            expected_keywords_json,
            required,
            weight,
            created_at,
            updated_at
        FROM template_anchors
        WHERE template_id = %s
        ORDER BY id ASC
    """
    return _format_datetime_rows(fetch_all(sql, (template_id,)))


def get_template_sample_by_id(sample_id: int):
    sql = """
        SELECT
            ts.id,
            ts.template_id,
            ts.sample_name,
            ts.image_path,
            ts.image_width,
            ts.image_height,
            ts.aspect_ratio,
            ts.sample_type,
            t.template_code
        FROM template_samples ts
        JOIN templates t ON t.id = ts.template_id
        WHERE ts.id = %s
        LIMIT 1
    """
    return fetch_one(sql, (sample_id,))


def create_template(bank_id, template_code, template_name, version_label, created_by=None):
    sql = """
        INSERT INTO templates (
            bank_id,
            template_code,
            template_name,
            version_label,
            status,
            created_by
        )
        VALUES (%s, %s, %s, %s, 'draft', %s)
    """
    return execute_insert(sql, (bank_id, template_code, template_name, version_label or None, created_by))


def create_template_sample(
    template_id,
    sample_name,
    image_path,
    image_width=None,
    image_height=None,
    aspect_ratio=None,
    uploaded_by=None,
    notes=None,
):
    sql = """
        INSERT INTO template_samples (
            template_id,
            sample_name,
            image_path,
            image_width,
            image_height,
            aspect_ratio,
            sample_type,
            uploaded_by,
            notes
        )
        VALUES (%s, %s, %s, %s, %s, %s, 'create_sample', %s, %s)
    """
    return execute_insert(
        sql,
        (
            template_id,
            sample_name,
            image_path,
            image_width,
            image_height,
            aspect_ratio,
            uploaded_by,
            notes,
        ),
    )


def create_template_field(
    template_id,
    field_name,
    display_name,
    field_type,
    x1,
    y1,
    x2,
    y2,
    required=False,
    crop_margin=0.01,
    sort_order=0,
):
    sql = """
        INSERT INTO template_fields (
            template_id,
            field_name,
            display_name,
            field_type,
            x1,
            y1,
            x2,
            y2,
            required,
            crop_margin,
            sort_order,
            is_active
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
    """
    return execute_insert(
        sql,
        (
            template_id,
            field_name,
            display_name,
            field_type,
            x1,
            y1,
            x2,
            y2,
            bool(required),
            crop_margin,
            sort_order,
        ),
    )


def create_template_anchor(
    template_id,
    anchor_name,
    anchor_type,
    x1,
    y1,
    x2,
    y2,
    expected_keywords_json=None,
    required=False,
    weight=1.0,
):
    sql = """
        INSERT INTO template_anchors (
            template_id,
            anchor_name,
            anchor_type,
            x1,
            y1,
            x2,
            y2,
            expected_keywords_json,
            required,
            weight
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    return execute_insert(
        sql,
        (
            template_id,
            anchor_name,
            anchor_type,
            x1,
            y1,
            x2,
            y2,
            expected_keywords_json,
            bool(required),
            weight,
        ),
    )



def update_template_field_box(template_id, field_id, x1, y1, x2, y2):
    sql = """
        UPDATE template_fields
        SET x1 = %s, y1 = %s, x2 = %s, y2 = %s
        WHERE id = %s AND template_id = %s
    """
    return execute_sql(sql, (x1, y1, x2, y2, field_id, template_id))


def update_template_anchor_box(template_id, anchor_id, x1, y1, x2, y2):
    sql = """
        UPDATE template_anchors
        SET x1 = %s, y1 = %s, x2 = %s, y2 = %s
        WHERE id = %s AND template_id = %s
    """
    return execute_sql(sql, (x1, y1, x2, y2, anchor_id, template_id))
