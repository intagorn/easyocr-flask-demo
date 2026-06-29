const hybridOcrForm = document.getElementById("hybridOcrForm");
const hybridImageInput = document.getElementById("hybridImageInput");
const hybridSubmitBtn = document.getElementById("hybridSubmitBtn");
const hybridStatusText = document.getElementById("hybridStatusText");
const hybridPreviewImage = document.getElementById("hybridPreviewImage");
const hybridBoxLayer = document.getElementById("hybridBoxLayer");
const hybridExtractedFields = document.getElementById("hybridExtractedFields");
const hybridQrOutput = document.getElementById("hybridQrOutput");
const hybridJsonOutput = document.getElementById("hybridJsonOutput");

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
    hybridPreviewImage.src = url;
    hybridPreviewImage.style.display = "block";
    hybridBoxLayer.innerHTML = "";
}

function drawEvidenceBoxes(data) {
    hybridBoxLayer.innerHTML = "";

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
        hybridBoxLayer.appendChild(div);
    }
}

function renderExtractedFields(data) {
    const fields = data.extraction?.fields || {};
    const keys = Object.keys(fields);

    if (keys.length === 0) {
        hybridExtractedFields.innerHTML = '<p class="note">No extracted fields.</p>';
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
        html += `<h3>Extraction Warnings</h3><ul>`;
        for (const warning of data.extraction.warnings) {
            html += `<li>${escapeHtml(warning)}</li>`;
        }
        html += `</ul>`;
    }

    hybridExtractedFields.innerHTML = html;
}

hybridImageInput.addEventListener("change", function () {
    if (hybridImageInput.files && hybridImageInput.files.length > 0) {
        setPreview(hybridImageInput.files[0]);
    }
});

hybridOcrForm.addEventListener("submit", async function (event) {
    event.preventDefault();

    if (!hybridImageInput.files || hybridImageInput.files.length === 0) {
        alert("Please select an image.");
        return;
    }

    const file = hybridImageInput.files[0];
    setPreview(file);

    const formData = new FormData();
    formData.append("image", file);

    hybridSubmitBtn.disabled = true;
    hybridStatusText.textContent = "Running full OCR, QR extraction, and generic extraction...";
    hybridExtractedFields.innerHTML = '<p class="note">Processing...</p>';
    hybridQrOutput.value = "";
    hybridJsonOutput.value = "";

    try {
        const response = await fetch("/api/hybrid-ocr", {
            method: "POST",
            body: formData
        });

        const data = await response.json();

        hybridJsonOutput.value = JSON.stringify(data, null, 2);
        hybridQrOutput.value = JSON.stringify(data.qr_codes || [], null, 2);

        if (!response.ok || data.status !== "success") {
            hybridStatusText.textContent = "Error.";
            hybridExtractedFields.innerHTML = `<p class="note">Error: ${escapeHtml(data.message || "Unknown error")}</p>`;
            return;
        }

        renderExtractedFields(data);
        drawEvidenceBoxes(data);
        hybridStatusText.textContent = "Done.";

    } catch (error) {
        const errorResult = {
            status: "error",
            message: error.message
        };
        hybridJsonOutput.value = JSON.stringify(errorResult, null, 2);
        hybridExtractedFields.innerHTML = `<p class="note">Error: ${escapeHtml(error.message)}</p>`;
        hybridStatusText.textContent = "Error.";
    } finally {
        hybridSubmitBtn.disabled = false;
    }
});
