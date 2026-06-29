-- EasyOCR Bank Transfer Slip Template MVP Database
-- v2 field naming: use reference_id for เลขที่รายการ / รหัสอ้างอิง in normal bank-transfer slips
-- Target: MySQL 8.x / MySQL Workbench
-- Character set: utf8mb4 for Thai text

CREATE DATABASE IF NOT EXISTS easyocr_slip_demo
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE easyocr_slip_demo;

-- For development reset. Comment these DROP lines if you already have data.
SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS template_test_results;
DROP TABLE IF EXISTS template_samples;
DROP TABLE IF EXISTS template_fields;
DROP TABLE IF EXISTS template_anchors;
DROP TABLE IF EXISTS templates;
DROP TABLE IF EXISTS field_definitions;
DROP TABLE IF EXISTS bank_keywords;
DROP TABLE IF EXISTS banks;
SET FOREIGN_KEY_CHECKS = 1;

CREATE TABLE banks (
    id INT AUTO_INCREMENT PRIMARY KEY,
    bank_code VARCHAR(80) NOT NULL UNIQUE,
    bank_name_th VARCHAR(255) NOT NULL,
    bank_name_en VARCHAR(255) NULL,
    notes TEXT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE bank_keywords (
    id INT AUTO_INCREMENT PRIMARY KEY,
    bank_id INT NOT NULL,
    keyword VARCHAR(255) NOT NULL,
    keyword_type ENUM('thai_name', 'english_name', 'app_name', 'ocr_alias', 'short_name', 'other')
        NOT NULL DEFAULT 'other',
    weight FLOAT NOT NULL DEFAULT 1.0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_bank_keywords_bank
        FOREIGN KEY (bank_id) REFERENCES banks(id)
        ON DELETE CASCADE,

    UNIQUE KEY uq_bank_keyword (bank_id, keyword),
    INDEX idx_bank_keywords_keyword (keyword)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE field_definitions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    field_name VARCHAR(100) NOT NULL UNIQUE,
    display_name_th VARCHAR(255) NOT NULL,
    display_name_en VARCHAR(255) NULL,
    default_field_type ENUM(
        'text',
        'money',
        'long_number',
        'date',
        'time',
        'datetime',
        'account_mask',
        'bank_name',
        'thai_name',
        'status'
    ) NOT NULL DEFAULT 'text',
    is_required_default BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order INT NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE templates (
    id INT AUTO_INCREMENT PRIMARY KEY,
    bank_id INT NOT NULL,

    template_code VARCHAR(120) NOT NULL UNIQUE,
    template_name VARCHAR(255) NOT NULL,
    version_label VARCHAR(100) NULL,

    status ENUM('draft', 'testing', 'active', 'deprecated')
        NOT NULL DEFAULT 'draft',

    expected_width INT NULL,
    expected_height INT NULL,
    expected_aspect_ratio FLOAT NULL,

    description TEXT NULL,
    notes TEXT NULL,

    -- Optional flexible data. Useful for future fallback config/import/export.
    optional_keywords_json JSON NULL,
    template_config_json JSON NULL,

    created_by VARCHAR(100) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_templates_bank
        FOREIGN KEY (bank_id) REFERENCES banks(id),

    INDEX idx_templates_bank_status (bank_id, status),
    INDEX idx_templates_code (template_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE template_anchors (
    id INT AUTO_INCREMENT PRIMARY KEY,
    template_id INT NOT NULL,

    anchor_name VARCHAR(100) NOT NULL,
    anchor_type ENUM('key_area', 'logo_area', 'text_label', 'success_text', 'other')
        NOT NULL DEFAULT 'key_area',

    -- Normalized coordinates: 0.0 to 1.0 relative to image width/height.
    x1 FLOAT NOT NULL,
    y1 FLOAT NOT NULL,
    x2 FLOAT NOT NULL,
    y2 FLOAT NOT NULL,

    expected_keywords_json JSON NULL,
    required BOOLEAN NOT NULL DEFAULT FALSE,
    weight FLOAT NOT NULL DEFAULT 1.0,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_template_anchors_template
        FOREIGN KEY (template_id) REFERENCES templates(id)
        ON DELETE CASCADE,

    INDEX idx_template_anchors_template (template_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE template_fields (
    id INT AUTO_INCREMENT PRIMARY KEY,
    template_id INT NOT NULL,

    field_name VARCHAR(100) NOT NULL,
    display_name VARCHAR(255) NOT NULL,

    field_type ENUM(
        'text',
        'money',
        'long_number',
        'date',
        'time',
        'datetime',
        'account_mask',
        'bank_name',
        'thai_name',
        'status'
    ) NOT NULL DEFAULT 'text',

    -- Normalized coordinates: 0.0 to 1.0 relative to image width/height.
    x1 FLOAT NOT NULL,
    y1 FLOAT NOT NULL,
    x2 FLOAT NOT NULL,
    y2 FLOAT NOT NULL,

    required BOOLEAN NOT NULL DEFAULT FALSE,
    crop_margin FLOAT NOT NULL DEFAULT 0.01,
    sort_order INT NOT NULL DEFAULT 0,

    postprocess_rules_json JSON NULL,
    validation_rules_json JSON NULL,
    fallback_rules_json JSON NULL,

    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_template_fields_template
        FOREIGN KEY (template_id) REFERENCES templates(id)
        ON DELETE CASCADE,

    INDEX idx_template_fields_template (template_id),
    INDEX idx_template_fields_name (field_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE template_samples (
    id INT AUTO_INCREMENT PRIMARY KEY,
    template_id INT NOT NULL,

    sample_name VARCHAR(255) NULL,

    -- Store relative path from STORAGE_ROOT, not absolute path.
    -- Example: template_samples/krungthai_next_2026_a/sample_001.jpg
    image_path VARCHAR(500) NOT NULL,

    image_width INT NULL,
    image_height INT NULL,
    aspect_ratio FLOAT NULL,

    sample_type ENUM('create_sample', 'test_sample')
        NOT NULL DEFAULT 'create_sample',

    raw_ocr_json JSON NULL,
    notes TEXT NULL,

    uploaded_by VARCHAR(100) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_template_samples_template
        FOREIGN KEY (template_id) REFERENCES templates(id)
        ON DELETE CASCADE,

    INDEX idx_template_samples_template (template_id),
    INDEX idx_template_samples_type (sample_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE template_test_results (
    id INT AUTO_INCREMENT PRIMARY KEY,
    template_id INT NOT NULL,
    sample_id INT NOT NULL,

    status ENUM('success', 'partial_success', 'failed')
        NOT NULL DEFAULT 'partial_success',

    extracted_fields_json JSON NULL,
    missing_fields_json JSON NULL,
    low_confidence_fields_json JSON NULL,
    warnings_json JSON NULL,

    confidence_score FLOAT NULL,
    processing_time_seconds FLOAT NULL,

    tested_by VARCHAR(100) NULL,
    tested_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_template_test_results_template
        FOREIGN KEY (template_id) REFERENCES templates(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_template_test_results_sample
        FOREIGN KEY (sample_id) REFERENCES template_samples(id)
        ON DELETE CASCADE,

    INDEX idx_template_test_results_template (template_id),
    INDEX idx_template_test_results_sample (sample_id),
    INDEX idx_template_test_results_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -------------------------------------------------------------------
-- Seed: field definitions for slip extraction UI
-- -------------------------------------------------------------------
INSERT INTO field_definitions
(field_name, display_name_th, display_name_en, default_field_type, is_required_default, sort_order)
VALUES
('transfer_status', 'สถานะการโอน', 'Transfer status', 'status', FALSE, 10),
('reference_id', 'เลขที่รายการ / รหัสอ้างอิง', 'Reference ID', 'long_number', TRUE, 20),
('transaction_datetime', 'วันและเวลาทำรายการ', 'Transaction date and time', 'datetime', TRUE, 30),
('transaction_date', 'วันที่ทำรายการ', 'Transaction date', 'date', FALSE, 31),
('transaction_time', 'เวลาทำรายการ', 'Transaction time', 'time', FALSE, 32),
('sender_name', 'ชื่อผู้โอน', 'Sender name', 'thai_name', FALSE, 40),
('sender_bank', 'ธนาคารผู้โอน', 'Sender bank', 'bank_name', FALSE, 41),
('sender_account', 'บัญชีผู้โอน', 'Sender account', 'account_mask', FALSE, 42),
('receiver_name', 'ชื่อผู้รับ', 'Receiver name', 'thai_name', FALSE, 50),
('receiver_bank', 'ธนาคารผู้รับ', 'Receiver bank', 'bank_name', FALSE, 51),
('receiver_account', 'บัญชีผู้รับ', 'Receiver account', 'account_mask', FALSE, 52),
('amount', 'จำนวนเงิน', 'Amount', 'money', TRUE, 60),
('fee', 'ค่าธรรมเนียม', 'Fee', 'money', FALSE, 70),
('note', 'หมายเหตุ', 'Note', 'text', FALSE, 80);

-- -------------------------------------------------------------------
-- Seed: banks from provided list
-- bank_code values are practical internal codes for this project.
-- Some English names are left NULL if not needed/uncertain for MVP.
-- -------------------------------------------------------------------
INSERT INTO banks (bank_code, bank_name_th, bank_name_en, notes) VALUES
('bangkok_bank', 'ธนาคารกรุงเทพ', 'Bangkok Bank', NULL),
('kasikorn', 'ธนาคารกสิกรไทย', 'Kasikornbank', NULL),
('krungthai', 'ธนาคารกรุงไทย', 'Krungthai Bank', NULL),
('tmb', 'ธนาคารทหารไทย', 'TMB Bank', 'Legacy/common old name. Consider mapping to ttb in future if needed.'),
('scb', 'ธนาคารไทยพาณิชย์', 'Siam Commercial Bank', NULL),
('krungsri', 'ธนาคารกรุงศรีอยุธยา', 'Bank of Ayudhya', NULL),
('kiatnakin_phatra', 'ธนาคารเกียรตินาคิน', 'Kiatnakin Phatra Bank', NULL),
('cimb_thai', 'ธนาคารซีไอเอ็มบีไทย', 'CIMB Thai Bank', NULL),
('tisco', 'ธนาคารทิสโก้', 'TISCO Bank', NULL),
('thanachart', 'ธนาคารธนชาต', 'Thanachart Bank', 'Legacy/common old name. Consider mapping to ttb in future if needed.'),
('uob', 'ธนาคารยูโอบี', 'United Overseas Bank Thai', NULL),
('standard_chartered_thai', 'ธนาคารสแตนดาร์ดชาร์เตอร์ด (ไทย)', 'Standard Chartered Bank Thai', NULL),
('thai_credit', 'ธนาคารไทยเครดิตเพื่อรายย่อย', 'Thai Credit Bank', NULL),
('lh_bank', 'ธนาคารแลนด์ แอนด์ เฮาส์', 'Land and Houses Bank', NULL),
('icbc_thai', 'ธนาคารไอซีบีซี (ไทย)', 'ICBC Thai', NULL),
('sme_d_bank', 'ธนาคารพัฒนาวิสาหกิจขนาดกลางและขนาดย่อมแห่งประเทศไทย', NULL, NULL),
('baac', 'ธนาคารเพื่อการเกษตรและสหกรณ์การเกษตร', NULL, NULL),
('exim_thailand', 'ธนาคารเพื่อการส่งออกและนำเข้าแห่งประเทศไทย', NULL, NULL),
('gsb', 'ธนาคารออมสิน', 'Government Savings Bank', NULL),
('gh_bank', 'ธนาคารอาคารสงเคราะห์', NULL, NULL),
('islamic_bank_thailand', 'ธนาคารอิสลามแห่งประเทศไทย', NULL, NULL),
('bank_of_china_thai', 'ธนาคารแห่งประเทศจีน', 'Bank of China', NULL),
('sumitomo_mitsui_trust_thai', 'ธนาคารซูมิโตโม มิตซุย ทรัสต์ (ไทย)', NULL, NULL),
('hsbc', 'ธนาคารฮ่องกงและเซี้ยงไฮ้แบงกิ้งคอร์ปอเรชั่น จำกัด', 'HSBC', NULL);

-- -------------------------------------------------------------------
-- Seed: keyword aliases for bank detection.
-- These are practical OCR/demo aliases, not official-only names.
-- Add more aliases later from real OCR errors.
-- -------------------------------------------------------------------
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ธนาคารกรุงเทพ', 'thai_name', 2.0 FROM banks WHERE bank_code = 'bangkok_bank';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'กรุงเทพ', 'short_name', 1.5 FROM banks WHERE bank_code = 'bangkok_bank';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'Bangkok Bank', 'english_name', 1.5 FROM banks WHERE bank_code = 'bangkok_bank';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'BBL', 'short_name', 1.0 FROM banks WHERE bank_code = 'bangkok_bank';

INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ธนาคารกสิกรไทย', 'thai_name', 2.0 FROM banks WHERE bank_code = 'kasikorn';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'กสิกรไทย', 'short_name', 1.8 FROM banks WHERE bank_code = 'kasikorn';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'กสิกร', 'short_name', 1.2 FROM banks WHERE bank_code = 'kasikorn';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'KBank', 'english_name', 1.5 FROM banks WHERE bank_code = 'kasikorn';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'K+', 'app_name', 1.5 FROM banks WHERE bank_code = 'kasikorn';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ธ.กสิกรไทย', 'ocr_alias', 1.5 FROM banks WHERE bank_code = 'kasikorn';

INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ธนาคารกรุงไทย', 'thai_name', 2.0 FROM banks WHERE bank_code = 'krungthai';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'กรุงไทย', 'short_name', 1.8 FROM banks WHERE bank_code = 'krungthai';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'Krungthai', 'english_name', 1.5 FROM banks WHERE bank_code = 'krungthai';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'KTB', 'short_name', 1.0 FROM banks WHERE bank_code = 'krungthai';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'กรงไทย', 'ocr_alias', 1.0 FROM banks WHERE bank_code = 'krungthai';

INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ธนาคารทหารไทย', 'thai_name', 2.0 FROM banks WHERE bank_code = 'tmb';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ทหารไทย', 'short_name', 1.5 FROM banks WHERE bank_code = 'tmb';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'TMB', 'short_name', 1.5 FROM banks WHERE bank_code = 'tmb';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ttb', 'app_name', 1.0 FROM banks WHERE bank_code = 'tmb';

INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ธนาคารไทยพาณิชย์', 'thai_name', 2.0 FROM banks WHERE bank_code = 'scb';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ไทยพาณิชย์', 'short_name', 1.8 FROM banks WHERE bank_code = 'scb';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'SCB', 'short_name', 1.5 FROM banks WHERE bank_code = 'scb';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'Siam Commercial Bank', 'english_name', 1.0 FROM banks WHERE bank_code = 'scb';

INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ธนาคารกรุงศรีอยุธยา', 'thai_name', 2.0 FROM banks WHERE bank_code = 'krungsri';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'กรุงศรี', 'short_name', 1.8 FROM banks WHERE bank_code = 'krungsri';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'อยุธยา', 'short_name', 1.0 FROM banks WHERE bank_code = 'krungsri';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'Krungsri', 'english_name', 1.5 FROM banks WHERE bank_code = 'krungsri';

INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ธนาคารเกียรตินาคิน', 'thai_name', 2.0 FROM banks WHERE bank_code = 'kiatnakin_phatra';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'เกียรตินาคิน', 'short_name', 1.5 FROM banks WHERE bank_code = 'kiatnakin_phatra';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'KKP', 'short_name', 1.0 FROM banks WHERE bank_code = 'kiatnakin_phatra';

INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ธนาคารซีไอเอ็มบีไทย', 'thai_name', 2.0 FROM banks WHERE bank_code = 'cimb_thai';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ซีไอเอ็มบี', 'short_name', 1.5 FROM banks WHERE bank_code = 'cimb_thai';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'CIMB', 'short_name', 1.5 FROM banks WHERE bank_code = 'cimb_thai';

INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ธนาคารทิสโก้', 'thai_name', 2.0 FROM banks WHERE bank_code = 'tisco';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ทิสโก้', 'short_name', 1.5 FROM banks WHERE bank_code = 'tisco';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'TISCO', 'short_name', 1.5 FROM banks WHERE bank_code = 'tisco';

INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ธนาคารธนชาต', 'thai_name', 2.0 FROM banks WHERE bank_code = 'thanachart';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ธนชาต', 'short_name', 1.5 FROM banks WHERE bank_code = 'thanachart';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'Thanachart', 'english_name', 1.2 FROM banks WHERE bank_code = 'thanachart';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ttb', 'app_name', 1.0 FROM banks WHERE bank_code = 'thanachart';

INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ธนาคารยูโอบี', 'thai_name', 2.0 FROM banks WHERE bank_code = 'uob';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ยูโอบี', 'short_name', 1.5 FROM banks WHERE bank_code = 'uob';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'UOB', 'short_name', 1.5 FROM banks WHERE bank_code = 'uob';

INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ธนาคารสแตนดาร์ดชาร์เตอร์ด', 'thai_name', 2.0 FROM banks WHERE bank_code = 'standard_chartered_thai';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'สแตนดาร์ดชาร์เตอร์ด', 'short_name', 1.5 FROM banks WHERE bank_code = 'standard_chartered_thai';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'Standard Chartered', 'english_name', 1.5 FROM banks WHERE bank_code = 'standard_chartered_thai';

INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ธนาคารไทยเครดิตเพื่อรายย่อย', 'thai_name', 2.0 FROM banks WHERE bank_code = 'thai_credit';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ไทยเครดิต', 'short_name', 1.5 FROM banks WHERE bank_code = 'thai_credit';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'Thai Credit', 'english_name', 1.2 FROM banks WHERE bank_code = 'thai_credit';

INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ธนาคารแลนด์ แอนด์ เฮาส์', 'thai_name', 2.0 FROM banks WHERE bank_code = 'lh_bank';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'แลนด์ แอนด์ เฮาส์', 'short_name', 1.5 FROM banks WHERE bank_code = 'lh_bank';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'LH Bank', 'english_name', 1.2 FROM banks WHERE bank_code = 'lh_bank';

INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ธนาคารไอซีบีซี', 'thai_name', 2.0 FROM banks WHERE bank_code = 'icbc_thai';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ไอซีบีซี', 'short_name', 1.5 FROM banks WHERE bank_code = 'icbc_thai';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ICBC', 'short_name', 1.5 FROM banks WHERE bank_code = 'icbc_thai';

INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ธนาคารพัฒนาวิสาหกิจขนาดกลางและขนาดย่อมแห่งประเทศไทย', 'thai_name', 2.0 FROM banks WHERE bank_code = 'sme_d_bank';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'SME', 'short_name', 0.8 FROM banks WHERE bank_code = 'sme_d_bank';

INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ธนาคารเพื่อการเกษตรและสหกรณ์การเกษตร', 'thai_name', 2.0 FROM banks WHERE bank_code = 'baac';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ธ.ก.ส.', 'short_name', 1.5 FROM banks WHERE bank_code = 'baac';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'BAAC', 'short_name', 1.2 FROM banks WHERE bank_code = 'baac';

INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ธนาคารเพื่อการส่งออกและนำเข้าแห่งประเทศไทย', 'thai_name', 2.0 FROM banks WHERE bank_code = 'exim_thailand';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'EXIM', 'short_name', 1.2 FROM banks WHERE bank_code = 'exim_thailand';

INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ธนาคารออมสิน', 'thai_name', 2.0 FROM banks WHERE bank_code = 'gsb';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ออมสิน', 'short_name', 1.5 FROM banks WHERE bank_code = 'gsb';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'GSB', 'short_name', 1.2 FROM banks WHERE bank_code = 'gsb';

INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ธนาคารอาคารสงเคราะห์', 'thai_name', 2.0 FROM banks WHERE bank_code = 'gh_bank';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ธอส.', 'short_name', 1.5 FROM banks WHERE bank_code = 'gh_bank';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'GHB', 'short_name', 1.2 FROM banks WHERE bank_code = 'gh_bank';

INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ธนาคารอิสลามแห่งประเทศไทย', 'thai_name', 2.0 FROM banks WHERE bank_code = 'islamic_bank_thailand';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'อิสลาม', 'short_name', 1.0 FROM banks WHERE bank_code = 'islamic_bank_thailand';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'Islamic Bank', 'english_name', 1.2 FROM banks WHERE bank_code = 'islamic_bank_thailand';

INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ธนาคารแห่งประเทศจีน', 'thai_name', 2.0 FROM banks WHERE bank_code = 'bank_of_china_thai';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'Bank of China', 'english_name', 1.5 FROM banks WHERE bank_code = 'bank_of_china_thai';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'BOC', 'short_name', 1.0 FROM banks WHERE bank_code = 'bank_of_china_thai';

INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ธนาคารซูมิโตโม มิตซุย ทรัสต์', 'thai_name', 2.0 FROM banks WHERE bank_code = 'sumitomo_mitsui_trust_thai';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ซูมิโตโม', 'short_name', 1.2 FROM banks WHERE bank_code = 'sumitomo_mitsui_trust_thai';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'Sumitomo', 'english_name', 1.2 FROM banks WHERE bank_code = 'sumitomo_mitsui_trust_thai';

INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ธนาคารฮ่องกงและเซี้ยงไฮ้แบงกิ้งคอร์ปอเรชั่น', 'thai_name', 2.0 FROM banks WHERE bank_code = 'hsbc';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'ฮ่องกงและเซี้ยงไฮ้', 'short_name', 1.0 FROM banks WHERE bank_code = 'hsbc';
INSERT INTO bank_keywords (bank_id, keyword, keyword_type, weight)
SELECT id, 'HSBC', 'short_name', 1.5 FROM banks WHERE bank_code = 'hsbc';

-- Useful quick check queries
SELECT COUNT(*) AS bank_count FROM banks;
SELECT COUNT(*) AS keyword_count FROM bank_keywords;
SELECT * FROM field_definitions ORDER BY sort_order;
