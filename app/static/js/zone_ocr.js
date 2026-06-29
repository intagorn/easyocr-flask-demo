const zoneOcrForm = document.getElementById("zoneOcrForm");
const zoneDetectionMode = document.getElementById("zoneDetectionMode");
const zoneTemplateSelect = document.getElementById("zoneTemplateSelect");
const zoneImageInput = document.getElementById("zoneImageInput");
const zoneSubmitBtn = document.getElementById("zoneSubmitBtn");
const zoneStatusText = document.getElementById("zoneStatusText");
const zonePreviewImage = document.getElementById("zonePreviewImage");
const zoneBoxLayer = document.getElementById("zoneBoxLayer");
const zoneExtractedFields = document.getElementById("zoneExtractedFields");
const zoneDebugOutput = document.getElementById("zoneDebugOutput");
const zoneJsonOutput = document.getElementById("zoneJsonOutput");

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function setPreview(file) {
    const url = URL.createObjectURL(file);
    zonePreviewImage.src = url;
    zonePreviewImage.style.display = "block";
    zoneBoxLayer.innerHTML = "";
}

function drawBoxes(data) {
    zoneBoxLayer.innerHTML = "";

    const boxes = data.evidence_boxes || [];
    for (const box of boxes) {
        const norm = box.bbox_norm;
        if (!norm || norm.length !== 4) continue;

        const div = document.createElement("div");
        div.className = "hybrid-evidence-box";

        if (box.source === "qr_detector") {
            div.classList.add("qr-evidence-box");
        } else if (box.source === "template_zone") {
            div.classList.add("template-zone-box");
        } else if (box.source === "zone_matched_ocr") {
            div.classList.add("zone-matched-ocr-box");
        }

        div.style.left = `${norm[0] * 100}%`;
        div.style.top = `${norm[1] * 100}%`;
        div.style.width = `${(norm[2] - norm[0]) * 100}%`;
        div.style.height = `${(norm[3] - norm[1]) * 100}%`;

        div.title = `${box.source || ""}\n${box.field_name || ""}\n${box.method || ""}\n${box.text || ""}`;
        zoneBoxLayer.appendChild(div);
    }
}

function renderFields(data) {
    const fields = data.extraction?.fields || {};
    const keys = Object.keys(fields);

    if (keys.length === 0) {
        zoneExtractedFields.innerHTML = '<p class="note">No extracted fields.</p>';
        return;
    }

    let html = `
        <table>
            <thead>
                <tr>
                    <th>Field</th>
                    <th>Value</th>
                    <th>Raw Value</th>
                    <th>Method</th>
                    <th>Confidence</th>
                    <th>Zone Candidate</th>
                    <th>Warnings</th>
                </tr>
            </thead>
            <tbody>
    `;

    for (const key of keys) {
        const field = fields[key] || {};
        const zoneCandidate = field.zone_candidate ? `${field.zone_candidate.value || ""} (${field.zone_candidate.confidence ?? ""})` : "";
        const warnings = (field.warnings || []).join("; ");
        html += `
            <tr>
                <td><code>${escapeHtml(key)}</code></td>
                <td><strong>${escapeHtml(field.value ?? "")}</strong></td>
                <td>${escapeHtml(field.raw_value ?? "")}</td>
                <td>${escapeHtml(field.method ?? "")}</td>
                <td>${field.confidence ?? ""}</td>
                <td>${escapeHtml(zoneCandidate)}</td>
                <td>${escapeHtml(warnings)}</td>
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

    zoneExtractedFields.innerHTML = html;
}

zoneImageInput.addEventListener("change", function () {
    if (zoneImageInput.files && zoneImageInput.files.length > 0) {
        setPreview(zoneImageInput.files[0]);
    }
});

zoneOcrForm.addEventListener("submit", async function (event) {
    event.preventDefault();

    if (!zoneImageInput.files || zoneImageInput.files.length === 0) {
        alert("Please select an image.");
        return;
    }

    if (zoneDetectionMode.value === "manual" && !zoneTemplateSelect.value) {
        alert("Please select a template for manual mode.");
        return;
    }

    const file = zoneImageInput.files[0];
    setPreview(file);

    const formData = new FormData();
    formData.append("image", file);
    formData.append("detection_mode", zoneDetectionMode.value);
    if (zoneTemplateSelect.value) {
        formData.append("template_id", zoneTemplateSelect.value);
    }

    zoneSubmitBtn.disabled = true;
    zoneStatusText.textContent = "Running full OCR, generic rules, QR extraction, and template-zone matching...";
    zoneExtractedFields.innerHTML = '<p class="note">Processing...</p>';
    zoneDebugOutput.value = "";
    zoneJsonOutput.value = "";

    try {
        const response = await fetch("/api/zone-ocr", {
            method: "POST",
            body: formData
        });

        const data = await response.json();
        zoneJsonOutput.value = JSON.stringify(data, null, 2);

        const debug = {
            selected_template: data.selected_template,
            detection: data.detection,
            zone_fields: data.zone_fields,
            merge_report: data.extraction?.merge_report,
            qr_codes: data.qr_codes,
            warnings: data.warnings
        };
        zoneDebugOutput.value = JSON.stringify(debug, null, 2);

        if (!response.ok || data.status !== "success") {
            zoneStatusText.textContent = "Error.";
            zoneExtractedFields.innerHTML = `<p class="note">Error: ${escapeHtml(data.message || "Unknown error")}</p>`;
            return;
        }

        renderFields(data);
        drawBoxes(data);
        zoneStatusText.textContent = "Done.";

    } catch (error) {
        const errorResult = {
            status: "error",
            message: error.message
        };
        zoneJsonOutput.value = JSON.stringify(errorResult, null, 2);
        zoneExtractedFields.innerHTML = `<p class="note">Error: ${escapeHtml(error.message)}</p>`;
        zoneStatusText.textContent = "Error.";
    } finally {
        zoneSubmitBtn.disabled = false;
    }
});
