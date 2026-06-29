const templateOcrForm = document.getElementById("templateOcrForm");
const templateSelect = document.getElementById("templateSelect");
const templateImageInput = document.getElementById("templateImageInput");
const templateOcrSubmitBtn = document.getElementById("templateOcrSubmitBtn");
const templateOcrStatusText = document.getElementById("templateOcrStatusText");
const templateOcrJsonOutput = document.getElementById("templateOcrJsonOutput");
const templateExtractedFields = document.getElementById("templateExtractedFields");
const templateDetectionView = document.getElementById("templateDetectionView");
const manualTemplateBlock = document.getElementById("manualTemplateBlock");

function getDetectionMode() {
    const checked = document.querySelector('input[name="detection_mode"]:checked');
    return checked ? checked.value : "manual";
}

function updateModeUi() {
    const mode = getDetectionMode();
    manualTemplateBlock.style.display = mode === "manual" ? "block" : "none";
}

document.querySelectorAll('input[name="detection_mode"]').forEach(function (radio) {
    radio.addEventListener("change", updateModeUi);
});

function renderExtractedFields(data) {
    const fields = data.extracted_fields || {};
    const keys = Object.keys(fields);

    if (keys.length === 0) {
        templateExtractedFields.innerHTML = '<p class="note">No extracted fields.</p>';
        return;
    }

    let html = `
        <table>
            <thead>
                <tr>
                    <th>Field</th>
                    <th>Display Name</th>
                    <th>Value</th>
                    <th>Raw OCR Text</th>
                    <th>Confidence</th>
                    <th>Type</th>
                </tr>
            </thead>
            <tbody>
    `;

    for (const key of keys) {
        const field = fields[key] || {};
        html += `
            <tr>
                <td><code>${escapeHtml(key)}</code></td>
                <td>${escapeHtml(field.display_name || "")}</td>
                <td><strong>${escapeHtml(field.value || "")}</strong></td>
                <td>${escapeHtml(field.raw_text || "")}</td>
                <td>${field.confidence ?? ""}</td>
                <td>${escapeHtml(field.field_type || "")}</td>
            </tr>
        `;
    }

    html += "</tbody></table>";

    if (data.warnings && data.warnings.length > 0) {
        html += `<h3>Warnings</h3><ul>`;
        for (const warning of data.warnings) {
            html += `<li>${escapeHtml(warning)}</li>`;
        }
        html += `</ul>`;
    }

    templateExtractedFields.innerHTML = html;
}

function renderTemplateDetection(data) {
    const detection = data.template_detection;
    if (!detection) {
        templateDetectionView.innerHTML = '<p class="note">Manual template selection was used, so no auto-detection result is shown.</p>';
        return;
    }

    const selected = detection.selected_template;
    const candidates = detection.candidates || [];

    let html = "";

    if (selected) {
        html += `
            <p><strong>Selected template:</strong> ${escapeHtml(selected.template_code)} | ${escapeHtml(selected.template_name)}</p>
            <p><strong>Confidence:</strong> ${escapeHtml(detection.confidence || "")}</p>
            <p><strong>Score:</strong> ${selected.score}</p>
        `;
    } else {
        html += `
            <p><strong>Status:</strong> Could not confidently select a template.</p>
            <p><strong>Confidence:</strong> ${escapeHtml(detection.confidence || "low")}</p>
            <p class="note">Please switch to Manual template selection and choose one of the candidates below.</p>
        `;
    }

    if (candidates.length > 0) {
        html += `
            <h3>Candidate Templates</h3>
            <table>
                <thead>
                    <tr>
                        <th>Score</th>
                        <th>Template</th>
                        <th>Bank</th>
                        <th>Fields</th>
                        <th>Matched Keywords</th>
                        <th>Reasons</th>
                        <th>Use Manually</th>
                    </tr>
                </thead>
                <tbody>
        `;

        for (const candidate of candidates) {
            html += `
                <tr>
                    <td>${candidate.score}</td>
                    <td><code>${escapeHtml(candidate.template_code)}</code><br>${escapeHtml(candidate.template_name)}</td>
                    <td>${escapeHtml(candidate.bank_name_th || "")}</td>
                    <td>${candidate.field_count ?? ""}</td>
                    <td>${escapeHtml((candidate.matched_keywords || []).join(", "))}</td>
                    <td>${escapeHtml((candidate.reasons || []).slice(0, 5).join(" | "))}</td>
                    <td><button type="button" class="candidate-use-btn" data-template-id="${candidate.template_id}">Select</button></td>
                </tr>
            `;
        }

        html += "</tbody></table>";
    }

    templateDetectionView.innerHTML = html;

    document.querySelectorAll(".candidate-use-btn").forEach(function (button) {
        button.addEventListener("click", function () {
            const templateId = button.getAttribute("data-template-id");
            document.querySelector('input[name="detection_mode"][value="manual"]').checked = true;
            updateModeUi();
            templateSelect.value = templateId;
            templateOcrStatusText.textContent = "Candidate selected. Click Run Template OCR again in manual mode.";
        });
    });
}

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

templateOcrForm.addEventListener("submit", async function (event) {
    event.preventDefault();

    const detectionMode = getDetectionMode();

    if (detectionMode === "manual" && !templateSelect.value) {
        alert("Please select a template, or switch to Auto Detect Template.");
        return;
    }

    if (!templateImageInput.files || templateImageInput.files.length === 0) {
        alert("Please select an image.");
        return;
    }

    const formData = new FormData();
    formData.append("detection_mode", detectionMode);
    formData.append("template_id", templateSelect.value || "");
    formData.append("image", templateImageInput.files[0]);

    templateOcrSubmitBtn.disabled = true;
    templateOcrStatusText.textContent = detectionMode === "auto"
        ? "Running full-image OCR to detect template, then extracting fields..."
        : "Running template OCR. This may take some time because each field crop is OCRed separately...";
    templateOcrJsonOutput.value = "";
    templateDetectionView.innerHTML = '<p class="note">Processing...</p>';
    templateExtractedFields.innerHTML = '<p class="note">Processing...</p>';

    try {
        const response = await fetch("/api/template-ocr", {
            method: "POST",
            body: formData
        });

        const data = await response.json();
        templateOcrJsonOutput.value = JSON.stringify(data, null, 2);

        if (data.status === "needs_template_selection") {
            renderTemplateDetection(data);
            templateExtractedFields.innerHTML = '<p class="note">No extraction was run because template detection was uncertain.</p>';
            templateOcrStatusText.textContent = "Template detection uncertain. Please select manually.";
            return;
        }

        if (!response.ok || data.status !== "success") {
            templateOcrStatusText.textContent = "Error.";
            templateDetectionView.innerHTML = `<p class="note">Error: ${escapeHtml(data.message || "Unknown error")}</p>`;
            templateExtractedFields.innerHTML = `<p class="note">Error: ${escapeHtml(data.message || "Unknown error")}</p>`;
            return;
        }

        renderTemplateDetection(data);
        renderExtractedFields(data);
        templateOcrStatusText.textContent = "Done.";

    } catch (error) {
        const errorResult = {
            status: "error",
            message: error.message
        };

        templateOcrJsonOutput.value = JSON.stringify(errorResult, null, 2);
        templateDetectionView.innerHTML = `<p class="note">Error: ${escapeHtml(error.message)}</p>`;
        templateExtractedFields.innerHTML = `<p class="note">Error: ${escapeHtml(error.message)}</p>`;
        templateOcrStatusText.textContent = "Error.";
    } finally {
        templateOcrSubmitBtn.disabled = false;
    }
});

updateModeUi();
