const genericRulesForm = document.getElementById("genericRulesForm");
const genericRulesImageInput = document.getElementById("genericRulesImageInput");
const genericRulesSubmitBtn = document.getElementById("genericRulesSubmitBtn");
const genericRulesStatusText = document.getElementById("genericRulesStatusText");
const genericRulesPreviewImage = document.getElementById("genericRulesPreviewImage");
const genericRulesBoxLayer = document.getElementById("genericRulesBoxLayer");
const genericRulesExtractedFields = document.getElementById("genericRulesExtractedFields");
const genericRulesRawText = document.getElementById("genericRulesRawText");
const genericRulesQrOutput = document.getElementById("genericRulesQrOutput");
const genericRulesJsonOutput = document.getElementById("genericRulesJsonOutput");

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
    genericRulesPreviewImage.src = url;
    genericRulesPreviewImage.style.display = "block";
    genericRulesBoxLayer.innerHTML = "";
}

function drawEvidenceBoxes(data) {
    genericRulesBoxLayer.innerHTML = "";

    const boxes = data.evidence_boxes || [];
    for (const box of boxes) {
        const norm = box.bbox_norm;
        if (!norm || norm.length !== 4) continue;

        const div = document.createElement("div");
        div.className = "hybrid-evidence-box";

        if (box.source === "qr_detector") {
            div.classList.add("qr-evidence-box");
        }

        div.style.left = `${norm[0] * 100}%`;
        div.style.top = `${norm[1] * 100}%`;
        div.style.width = `${(norm[2] - norm[0]) * 100}%`;
        div.style.height = `${(norm[3] - norm[1]) * 100}%`;

        div.title = `${box.field_name || ""}\n${box.method || ""}\n${box.text || ""}`;
        genericRulesBoxLayer.appendChild(div);
    }
}

function renderExtractedFields(data) {
    const fields = data.extraction?.fields || {};
    const keys = Object.keys(fields);

    if (keys.length === 0) {
        genericRulesExtractedFields.innerHTML = '<p class="note">No extracted fields.</p>';
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
                    <th>Warnings</th>
                </tr>
            </thead>
            <tbody>
    `;

    for (const key of keys) {
        const field = fields[key] || {};
        const warnings = (field.warnings || []).join("; ");
        html += `
            <tr>
                <td><code>${escapeHtml(key)}</code></td>
                <td><strong>${escapeHtml(field.value ?? "")}</strong></td>
                <td>${escapeHtml(field.raw_value ?? "")}</td>
                <td>${escapeHtml(field.method ?? "")}</td>
                <td>${field.confidence ?? ""}</td>
                <td>${escapeHtml(warnings)}</td>
            </tr>
        `;
    }

    html += "</tbody></table>";

    if (data.extraction?.warnings && data.extraction.warnings.length > 0) {
        html += `<h3>Warnings</h3><ul>`;
        for (const warning of data.extraction.warnings) {
            html += `<li>${escapeHtml(warning)}</li>`;
        }
        html += `</ul>`;
    }

    if (data.limitations && data.limitations.length > 0) {
        html += `<h3>Rule Limitations</h3><ul>`;
        for (const limitation of data.limitations) {
            html += `<li>${escapeHtml(limitation)}</li>`;
        }
        html += `</ul>`;
    }

    genericRulesExtractedFields.innerHTML = html;
}

genericRulesImageInput.addEventListener("change", function () {
    if (genericRulesImageInput.files && genericRulesImageInput.files.length > 0) {
        setPreview(genericRulesImageInput.files[0]);
    }
});

genericRulesForm.addEventListener("submit", async function (event) {
    event.preventDefault();

    if (!genericRulesImageInput.files || genericRulesImageInput.files.length === 0) {
        alert("Please select an image.");
        return;
    }

    const file = genericRulesImageInput.files[0];
    setPreview(file);

    const formData = new FormData();
    formData.append("image", file);

    genericRulesSubmitBtn.disabled = true;
    genericRulesStatusText.textContent = "Running EasyOCR once, generic rules, and QR extraction...";
    genericRulesExtractedFields.innerHTML = '<p class="note">Processing...</p>';
    genericRulesRawText.value = "";
    genericRulesQrOutput.value = "";
    genericRulesJsonOutput.value = "";

    try {
        const response = await fetch("/api/generic-rules-ocr", {
            method: "POST",
            body: formData
        });

        const data = await response.json();

        genericRulesJsonOutput.value = JSON.stringify(data, null, 2);
        genericRulesQrOutput.value = JSON.stringify(data.qr_codes || [], null, 2);
        genericRulesRawText.value = data.extraction?.raw_full_text || data.ocr_result?.result?.full_text || "";

        if (!response.ok || data.status !== "success") {
            genericRulesStatusText.textContent = "Error.";
            genericRulesExtractedFields.innerHTML = `<p class="note">Error: ${escapeHtml(data.message || "Unknown error")}</p>`;
            return;
        }

        renderExtractedFields(data);
        drawEvidenceBoxes(data);
        genericRulesStatusText.textContent = "Done.";

    } catch (error) {
        const errorResult = {
            status: "error",
            message: error.message
        };
        genericRulesJsonOutput.value = JSON.stringify(errorResult, null, 2);
        genericRulesExtractedFields.innerHTML = `<p class="note">Error: ${escapeHtml(error.message)}</p>`;
        genericRulesStatusText.textContent = "Error.";
    } finally {
        genericRulesSubmitBtn.disabled = false;
    }
});
