const imageStage = document.getElementById("imageStage");
const sampleImage = document.getElementById("sampleImage");
const drawBox = document.getElementById("drawBox");
const boxMode = document.getElementById("boxMode");
const fieldControls = document.getElementById("fieldControls");
const anchorControls = document.getElementById("anchorControls");
const coordPreview = document.getElementById("coordPreview");
const saveBoxBtn = document.getElementById("saveBoxBtn");
const boxStatus = document.getElementById("boxStatus");

const fieldName = document.getElementById("fieldName");
const displayName = document.getElementById("displayName");
const fieldType = document.getElementById("fieldType");

let isDrawing = false;
let startX = 0;
let startY = 0;
let currentBox = null;

function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
}

function round4(value) {
    return Math.round(value * 10000) / 10000;
}

function getStagePoint(event) {
    const rect = imageStage.getBoundingClientRect();
    const x = clamp((event.clientX - rect.left) / rect.width, 0, 1);
    const y = clamp((event.clientY - rect.top) / rect.height, 0, 1);
    return { x, y };
}

function updateDrawBox(x1, y1, x2, y2) {
    const left = Math.min(x1, x2);
    const top = Math.min(y1, y2);
    const width = Math.abs(x2 - x1);
    const height = Math.abs(y2 - y1);

    drawBox.style.left = `${left * 100}%`;
    drawBox.style.top = `${top * 100}%`;
    drawBox.style.width = `${width * 100}%`;
    drawBox.style.height = `${height * 100}%`;
    drawBox.style.display = "block";

    currentBox = {
        x1: round4(left),
        y1: round4(top),
        x2: round4(left + width),
        y2: round4(top + height)
    };

    coordPreview.value = `[${currentBox.x1}, ${currentBox.y1}, ${currentBox.x2}, ${currentBox.y2}]`;
}

function clearCurrentBox() {
    currentBox = null;
    drawBox.style.display = "none";
    coordPreview.value = "";
}

function setModeDisplay() {
    const mode = boxMode.value;
    if (mode === "field") {
        fieldControls.style.display = "block";
        anchorControls.style.display = "none";
    } else {
        fieldControls.style.display = "none";
        anchorControls.style.display = "block";
    }
}

function autoFillFieldTypeAndDisplay() {
    const selected = fieldName.options[fieldName.selectedIndex];
    const suggestedType = selected?.dataset?.type || "text";
    fieldType.value = suggestedType;

    if (!displayName.value || displayName.dataset.autofilled === "true") {
        displayName.value = fieldName.value;
        displayName.dataset.autofilled = "true";
    }
}

if (boxMode) {
    boxMode.addEventListener("change", setModeDisplay);
}

if (fieldName) {
    fieldName.addEventListener("change", autoFillFieldTypeAndDisplay);
}

if (displayName) {
    displayName.addEventListener("input", function () {
        displayName.dataset.autofilled = "false";
    });
}

if (imageStage) {
    imageStage.addEventListener("mousedown", function (event) {
        if (typeof savedEditEnabled === "function" && savedEditEnabled()) {
            return;
        }
        event.preventDefault();
        isDrawing = true;
        const p = getStagePoint(event);
        startX = p.x;
        startY = p.y;
        updateDrawBox(startX, startY, startX, startY);
        boxStatus.textContent = "Drawing...";
    });

    window.addEventListener("mousemove", function (event) {
        if (!isDrawing) return;
        const p = getStagePoint(event);
        updateDrawBox(startX, startY, p.x, p.y);
    });

    window.addEventListener("mouseup", function (event) {
        if (!isDrawing) return;
        isDrawing = false;
        const p = getStagePoint(event);
        updateDrawBox(startX, startY, p.x, p.y);

        if ((currentBox.x2 - currentBox.x1) < 0.005 || (currentBox.y2 - currentBox.y1) < 0.005) {
            boxStatus.textContent = "Box is too small. Please draw again.";
        } else {
            boxStatus.textContent = "Box ready. Fill settings and click Save Box.";
        }
    });
}

async function saveFieldBox() {
    const payload = {
        ...currentBox,
        field_name: fieldName.value,
        display_name: displayName.value || fieldName.value,
        field_type: fieldType.value,
        required: document.getElementById("fieldRequired").checked,
        crop_margin: Number(document.getElementById("cropMargin").value || 0.01)
    };

    const response = await fetch(`/api/templates/${window.TEMPLATE_ID}/fields`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
    });

    const data = await response.json();
    if (!response.ok || data.status !== "success") {
        throw new Error(data.message || "Could not save field.");
    }
    return data;
}

async function saveAnchorBox() {
    const payload = {
        ...currentBox,
        anchor_name: document.getElementById("anchorName").value,
        anchor_type: document.getElementById("anchorType").value,
        expected_keywords: document.getElementById("expectedKeywords").value,
        required: document.getElementById("anchorRequired").checked,
        weight: Number(document.getElementById("anchorWeight").value || 1.0)
    };

    const response = await fetch(`/api/templates/${window.TEMPLATE_ID}/anchors`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
    });

    const data = await response.json();
    if (!response.ok || data.status !== "success") {
        throw new Error(data.message || "Could not save anchor.");
    }
    return data;
}

if (saveBoxBtn) {
    saveBoxBtn.addEventListener("click", async function () {
        if (!currentBox) {
            boxStatus.textContent = "Please draw a box first.";
            return;
        }

        saveBoxBtn.disabled = true;
        boxStatus.textContent = "Saving...";

        try {
            if (boxMode.value === "field") {
                await saveFieldBox();
            } else {
                await saveAnchorBox();
            }

            boxStatus.textContent = "Saved. Reloading page...";
            window.location.reload();
        } catch (error) {
            boxStatus.textContent = "Error: " + error.message;
        } finally {
            saveBoxBtn.disabled = false;
        }
    });
}

setModeDisplay();
autoFillFieldTypeAndDisplay();


// ---------------------------------------------------------------------
// Saved-box visual editor
// ---------------------------------------------------------------------
const editSavedBoxesToggle = document.getElementById("editSavedBoxesToggle");
const saveEditedBoxBtn = document.getElementById("saveEditedBoxBtn");
const cancelEditBoxBtn = document.getElementById("cancelEditBoxBtn");
const editBoxStatus = document.getElementById("editBoxStatus");
const savedBoxes = Array.from(document.querySelectorAll(".editable-saved-box"));

let selectedSavedBox = null;
let selectedOriginalBox = null;
let editAction = null;
let editStartPoint = null;
let editStartBox = null;
let activeHandle = null;

function boxFromElement(el) {
    return {
        x1: Number(el.dataset.x1),
        y1: Number(el.dataset.y1),
        x2: Number(el.dataset.x2),
        y2: Number(el.dataset.y2)
    };
}

function setElementBox(el, box) {
    const safeBox = normalizeBox(box);
    el.dataset.x1 = String(round4(safeBox.x1));
    el.dataset.y1 = String(round4(safeBox.y1));
    el.dataset.x2 = String(round4(safeBox.x2));
    el.dataset.y2 = String(round4(safeBox.y2));

    el.style.left = `${safeBox.x1 * 100}%`;
    el.style.top = `${safeBox.y1 * 100}%`;
    el.style.width = `${(safeBox.x2 - safeBox.x1) * 100}%`;
    el.style.height = `${(safeBox.y2 - safeBox.y1) * 100}%`;

    if (selectedSavedBox === el) {
        coordPreview.value = `[${round4(safeBox.x1)}, ${round4(safeBox.y1)}, ${round4(safeBox.x2)}, ${round4(safeBox.y2)}]`;
    }
}

function normalizeBox(box) {
    let x1 = clamp(Math.min(box.x1, box.x2), 0, 1);
    let y1 = clamp(Math.min(box.y1, box.y2), 0, 1);
    let x2 = clamp(Math.max(box.x1, box.x2), 0, 1);
    let y2 = clamp(Math.max(box.y1, box.y2), 0, 1);

    const minSize = 0.006;
    if (x2 - x1 < minSize) {
        x2 = clamp(x1 + minSize, 0, 1);
        if (x2 === 1) x1 = 1 - minSize;
    }
    if (y2 - y1 < minSize) {
        y2 = clamp(y1 + minSize, 0, 1);
        if (y2 === 1) y1 = 1 - minSize;
    }

    return { x1, y1, x2, y2 };
}

function addResizeHandles(el) {
    if (el.querySelector(".resize-handle")) return;
    const handles = ["nw", "ne", "sw", "se", "n", "s", "w", "e"];
    for (const name of handles) {
        const handle = document.createElement("div");
        handle.className = `resize-handle handle-${name}`;
        handle.dataset.handle = name;
        el.appendChild(handle);
    }
}

function removeResizeHandles(el) {
    el.querySelectorAll(".resize-handle").forEach(h => h.remove());
}

function clearSavedBoxSelection() {
    if (selectedSavedBox) {
        selectedSavedBox.classList.remove("selected-saved-box");
        removeResizeHandles(selectedSavedBox);
    }
    selectedSavedBox = null;
    selectedOriginalBox = null;
    saveEditedBoxBtn.disabled = true;
    cancelEditBoxBtn.disabled = true;
}

function selectSavedBox(el) {
    clearSavedBoxSelection();
    selectedSavedBox = el;
    selectedOriginalBox = { ...boxFromElement(el) };
    el.classList.add("selected-saved-box");
    addResizeHandles(el);
    saveEditedBoxBtn.disabled = false;
    cancelEditBoxBtn.disabled = false;

    const kind = el.dataset.boxKind;
    const name = el.dataset.name;
    editBoxStatus.textContent = `Selected ${kind}: ${name}`;
    currentBox = boxFromElement(el);
    coordPreview.value = `[${round4(currentBox.x1)}, ${round4(currentBox.y1)}, ${round4(currentBox.x2)}, ${round4(currentBox.y2)}]`;
}

function savedEditEnabled() {
    return editSavedBoxesToggle && editSavedBoxesToggle.checked;
}

function setSavedBoxEditMode() {
    const enabled = savedEditEnabled();
    document.body.classList.toggle("saved-box-edit-enabled", enabled);

    if (!enabled) {
        clearSavedBoxSelection();
        editBoxStatus.textContent = "";
    } else {
        editBoxStatus.textContent = "Edit mode on. Click a saved box to adjust it.";
    }
}

function computeResizeBox(startBox, dx, dy, handle) {
    const box = { ...startBox };
    if (handle.includes("w")) box.x1 += dx;
    if (handle.includes("e")) box.x2 += dx;
    if (handle.includes("n")) box.y1 += dy;
    if (handle.includes("s")) box.y2 += dy;
    return normalizeBox(box);
}

function computeMoveBox(startBox, dx, dy) {
    const width = startBox.x2 - startBox.x1;
    const height = startBox.y2 - startBox.y1;

    let x1 = startBox.x1 + dx;
    let y1 = startBox.y1 + dy;

    x1 = clamp(x1, 0, 1 - width);
    y1 = clamp(y1, 0, 1 - height);

    return {
        x1,
        y1,
        x2: x1 + width,
        y2: y1 + height
    };
}

for (const el of savedBoxes) {
    el.addEventListener("mousedown", function (event) {
        if (!savedEditEnabled()) return;

        event.preventDefault();
        event.stopPropagation();

        selectSavedBox(el);

        editStartPoint = getStagePoint(event);
        editStartBox = boxFromElement(el);
        activeHandle = event.target?.dataset?.handle || null;
        editAction = activeHandle ? "resize" : "move";
    });
}

window.addEventListener("mousemove", function (event) {
    if (!selectedSavedBox || !editAction) return;

    const p = getStagePoint(event);
    const dx = p.x - editStartPoint.x;
    const dy = p.y - editStartPoint.y;

    let newBox;
    if (editAction === "move") {
        newBox = computeMoveBox(editStartBox, dx, dy);
    } else {
        newBox = computeResizeBox(editStartBox, dx, dy, activeHandle);
    }

    setElementBox(selectedSavedBox, newBox);
});

window.addEventListener("mouseup", function () {
    if (!editAction) return;
    editAction = null;
    activeHandle = null;
    if (selectedSavedBox) {
        currentBox = boxFromElement(selectedSavedBox);
        editBoxStatus.textContent = "Box adjusted. Click Save Edited Box to update database.";
    }
});

if (editSavedBoxesToggle) {
    editSavedBoxesToggle.addEventListener("change", setSavedBoxEditMode);
}

if (cancelEditBoxBtn) {
    cancelEditBoxBtn.addEventListener("click", function () {
        if (!selectedSavedBox || !selectedOriginalBox) return;
        setElementBox(selectedSavedBox, selectedOriginalBox);
        editBoxStatus.textContent = "Edit cancelled.";
        clearSavedBoxSelection();
    });
}

async function saveEditedSavedBox() {
    if (!selectedSavedBox) {
        editBoxStatus.textContent = "Please select a saved box first.";
        return;
    }

    const kind = selectedSavedBox.dataset.boxKind;
    const id = selectedSavedBox.dataset.boxId;
    const box = boxFromElement(selectedSavedBox);

    const endpoint = kind === "field"
        ? `/api/templates/${window.TEMPLATE_ID}/fields/${id}/box`
        : `/api/templates/${window.TEMPLATE_ID}/anchors/${id}/box`;

    const response = await fetch(endpoint, {
        method: "PATCH",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify(box)
    });

    const data = await response.json();
    if (!response.ok || data.status !== "success") {
        throw new Error(data.message || "Could not update box.");
    }

    return data;
}

if (saveEditedBoxBtn) {
    saveEditedBoxBtn.addEventListener("click", async function () {
        if (!selectedSavedBox) {
            editBoxStatus.textContent = "Please select a saved box first.";
            return;
        }

        saveEditedBoxBtn.disabled = true;
        editBoxStatus.textContent = "Saving edited box...";

        try {
            const result = await saveEditedSavedBox();
            if (result.affected_rows === 0) {
                editBoxStatus.textContent = "Saved request accepted. MySQL reported 0 changed rows, but this is allowed. Reloading page...";
            } else {
                editBoxStatus.textContent = "Saved. Reloading page...";
            }
            window.location.reload();
        } catch (error) {
            editBoxStatus.textContent = "Error: " + error.message;
            saveEditedBoxBtn.disabled = false;
        }
    });
}

setSavedBoxEditMode();
