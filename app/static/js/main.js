const form = document.getElementById("ocrForm");
const imageInput = document.getElementById("imageInput");
const jsonOutput = document.getElementById("jsonOutput");
const extractReport = document.getElementById("extractReport");
const statusText = document.getElementById("statusText");
const submitBtn = document.getElementById("submitBtn");

const fieldIds = [
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
    "receiver_account"
];

function setValue(id, value) {
    const el = document.getElementById(id);
    if (el) {
        el.value = value ?? "";
    }
}

function clearExtractedFields() {
    setValue("field_extraction_status", "");
    setValue("field_ocr_seconds", "");
    for (const id of fieldIds) {
        setValue("field_" + id, "");
    }
    extractReport.value = "";
}

function getFieldValue(extraction, fieldName) {
    const field = extraction?.fields?.[fieldName];
    if (!field) return "";
    if (field.value === null || field.value === undefined) return "";
    return field.value;
}

function populateExtractedFields(data) {
    const extraction = data.extraction || {};
    setValue("field_extraction_status", extraction.status || "");
    setValue("field_ocr_seconds", data.processing_time?.ocr_seconds ?? "");

    for (const id of fieldIds) {
        setValue("field_" + id, getFieldValue(extraction, id));
    }

    const report = {
        status: extraction.status,
        document_type: extraction.document_type,
        missing_fields: extraction.missing_fields || [],
        low_confidence_fields: extraction.low_confidence_fields || [],
        warnings: extraction.warnings || [],
        detected_bank_candidates: extraction.detected_bank_candidates || [],
        fields_detail: extraction.fields || {},
        normalized_lines: extraction.normalized_lines || []
    };

    extractReport.value = JSON.stringify(report, null, 2);
}

form.addEventListener("submit", async function (event) {
    event.preventDefault();

    if (!imageInput.files || imageInput.files.length === 0) {
        alert("Please select an image.");
        return;
    }

    const file = imageInput.files[0];
    const formData = new FormData();
    formData.append("image", file);

    jsonOutput.value = "";
    clearExtractedFields();
    statusText.textContent = "Processing OCR and rule extraction...";
    submitBtn.disabled = true;

    const startTime = performance.now();

    try {
        const response = await fetch("/api/ocr", {
            method: "POST",
            body: formData
        });

        const data = await response.json();

        const endTime = performance.now();
        const browserSeconds = ((endTime - startTime) / 1000).toFixed(4);

        data.processing_time = data.processing_time || {};
        data.processing_time.browser_roundtrip_seconds = Number(browserSeconds);

        populateExtractedFields(data);
        jsonOutput.value = JSON.stringify(data, null, 2);

        if (response.ok) {
            statusText.textContent = "Done.";
        } else {
            statusText.textContent = "Error.";
        }

    } catch (error) {
        const errorResult = {
            status: "error",
            message: error.message
        };

        jsonOutput.value = JSON.stringify(errorResult, null, 2);
        extractReport.value = JSON.stringify(errorResult, null, 2);
        statusText.textContent = "Error.";
    } finally {
        submitBtn.disabled = false;
    }
});
