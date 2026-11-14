const state = {
  documents: [],
  selected: null,
  previewId: null,
  previewFormat: null,
  page: 1,
  pageCount: 1,
  pageWidth: 0,
  pageHeight: 0,
  pageViewBox: null,
  zoom: 1,
  panX: 0,
  panY: 0,
  overlays: [],
  activeEvidence: null,
  objectUrl: null,
  renderToken: 0,
  licenseText: null,
  llmConfig: null,
  groqModel: null,
  geminiVlConfigured: false,
  geminiVlModel: null,
  geminiVisionConsent: false,
};

const $ = (id) => document.getElementById(id);
const documentList = $("document-list");
const image = $("drawing-image");
const imageStack = $("image-stack");
const evidenceLayer = $("evidence-layer");
let toastTimer;
let dragging = false;
let dragOrigin = null;

function showToast(message) {
  const toast = $("toast");
  toast.textContent = message;
  toast.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("visible"), 3200);
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch { /* Keep the HTTP status when the response is not JSON. */ }
    throw new Error(detail);
  }
  return response;
}

function extLabel(format) {
  return (format || "FILE").toUpperCase().slice(0, 4);
}

function displayName(path) {
  const parts = path.split("/");
  return parts[parts.length - 1] || path;
}

function humanSize(bytes) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function capabilitySummary(document) {
  return (document.capabilities || []).filter((cap) => cap.available).map((cap) => {
    const labels = {
      pdf_text: "Selectable text",
      pdf_render: "Page rendering",
      raster: "Raster image",
      svg_vector: "SVG vectors",
      dxf_geometry: "CAD geometry",
      ifc_entities: "IFC entities",
      ifc_geometry: "IFC geometry",
      ocr: "OCR",
      object_detection: "Detection",
    };
    return labels[cap.capability_type] || cap.capability_type.replaceAll("_", " ");
  });
}

async function loadDocuments() {
  try {
    const response = await api("/api/documents");
    state.documents = await response.json();
    $("document-count").textContent = state.documents.length.toLocaleString();
    populateSources();
    renderDocumentList();
    if (!state.selected) {
      const defaultDocument = state.documents.find((doc) =>
        doc.path === "data/ifc_models/bsc-esplanades_1807-ep-ar-v18.ifc"
      ) || state.documents.find((doc) => doc.format === "pdf") || state.documents[0];
      if (defaultDocument) selectDocument(defaultDocument.document_id);
    } else {
      const current = state.documents.find((doc) => doc.document_id === state.selected.document_id);
      if (current) selectDocument(current.document_id, false);
    }
  } catch (error) {
    showToast(`Could not load local documents: ${error.message}`);
  }
}

function populateSources() {
  const select = $("source-filter");
  const selected = select.value;
  const sources = [...new Set(state.documents.map((doc) => doc.source))].sort();
  select.innerHTML = '<option value="">All sources</option>';
  for (const source of sources) {
    const option = document.createElement("option");
    option.value = source;
    option.textContent = source;
    select.append(option);
  }
  select.value = sources.includes(selected) ? selected : "";
}

function renderDocumentList() {
  const query = $("document-search").value.trim().toLowerCase();
  const source = $("source-filter").value;
  const filtered = state.documents.filter((doc) => {
    const matchesText = !query || doc.path.toLowerCase().includes(query) || doc.source.toLowerCase().includes(query);
    return matchesText && (!source || doc.source === source);
  });
  const visible = filtered.slice(0, 160);
  documentList.replaceChildren();
  for (const doc of visible) {
    const button = document.createElement("button");
    button.className = `document-item${state.selected?.document_id === doc.document_id ? " active" : ""}`;
    button.setAttribute("role", "option");
    button.setAttribute("aria-selected", String(state.selected?.document_id === doc.document_id));
    button.title = doc.path;

    const icon = document.createElement("span");
    icon.className = `doc-icon ${doc.format}`;
    icon.textContent = extLabel(doc.format);
    const copy = document.createElement("span");
    copy.className = "doc-copy";
    const strong = document.createElement("strong");
    strong.textContent = displayName(doc.path);
    const small = document.createElement("small");
    small.textContent = `${doc.source} · ${humanSize(doc.size_bytes)}`;
    copy.append(strong, small);
    const dot = document.createElement("span");
    dot.className = "doc-ready";
    dot.textContent = doc.ingestion_status === "ready" ? "●" : "◌";
    dot.title = doc.ingestion_status === "uninspected"
      ? "Select this document to inspect its capabilities"
      : doc.ingestion_status === "ready"
        ? "Document inspected and ready"
        : "Document inspected with limitations";
    button.append(icon, copy, dot);
    button.addEventListener("click", () => selectDocument(doc.document_id));
    documentList.append(button);
  }
  $("document-list-note").textContent = filtered.length > visible.length
    ? `Showing ${visible.length} of ${filtered.length} · refine search to narrow`
    : `${filtered.length} document${filtered.length === 1 ? "" : "s"}`;
}

async function selectDocument(documentId, resetViewer = true) {
  const document = state.documents.find((item) => item.document_id === documentId);
  if (!document) return;
  try {
    const response = await api(`/api/documents/${documentId}`);
    const details = await response.json();
    state.selected = details;
    state.previewId = details.preview_document_id || details.document_id;
    const preview = state.documents.find((item) => item.document_id === state.previewId);
    state.previewFormat = details.preview_format || preview?.format || details.format;
    if (resetViewer) {
      state.page = 1;
      state.zoom = 1;
      state.panX = 0;
      state.panY = 0;
      state.overlays = [];
      state.activeEvidence = null;
    }
    renderDocumentList();
    renderSelectedDocument();
    await renderPreview();
    await loadLicense();
  } catch (error) {
    showToast(`Could not open document: ${error.message}`);
  }
}

function renderSelectedDocument() {
  const doc = state.selected;
  if (!doc) return;
  $("selected-file-icon").className = `mini-file-icon ${doc.format}`;
  $("selected-file-icon").textContent = extLabel(doc.format);
  $("selected-doc-name").textContent = displayName(doc.path);
  $("selected-doc-meta").textContent = `${doc.source} · ${humanSize(doc.size_bytes)}${doc.page_count ? ` · ${doc.page_count} pages` : ""}`;
  $("document-ready-tag").textContent = doc.ingestion_status === "ready" ? "READY" : "LIMITED";
  $("document-ready-tag").classList.toggle("limited", doc.ingestion_status !== "ready");
  $("canvas-file-icon").className = `file-icon ${state.previewFormat}`;
  $("canvas-file-icon").textContent = extLabel(state.previewFormat);
  $("canvas-title").textContent = displayName(doc.path);
  $("canvas-subtitle").textContent = doc.preview_relationship === "source document"
    ? `${doc.source} · ${doc.format.toUpperCase()} · ${doc.license_file || "user upload"}`
    : `${doc.preview_relationship} · source remains ${doc.format.toUpperCase()}`;
  $("source-credit").textContent = doc.license_credit || "";
  const capRow = $("capabilities-row");
  capRow.replaceChildren();
  for (const cap of doc.capabilities || []) {
    const chip = document.createElement("span");
    chip.className = `cap-chip${cap.available ? "" : " unavailable"}`;
    const dot = document.createElement("i");
    dot.className = "cap-dot";
    const label = cap.capability_type.replaceAll("_", " ");
    chip.append(dot, document.createTextNode(label));
    chip.title = cap.available ? label : (cap.limitations || []).join(" ");
    capRow.append(chip);
  }
  renderSuggestions(doc);
  $("ask-button").disabled = false;
}

function renderSuggestions(doc) {
  const suggestions = $("suggestions");
  suggestions.replaceChildren();
  const examples = {
    ifc: [
      "How many doors are there in this model?",
      "How many windows are there in this model?",
    ],
    pdf: [
      "Find the room schedule and show its text evidence.",
      "What text mentions doors in this drawing?",
    ],
    dxf: [
      "How many doors are represented by named blocks?",
      "How many windows are represented by named blocks?",
    ],
    png: ["How many windows are shown on this floor plan?"],
    jpg: ["Find readable text on this drawing."],
    jpeg: ["Find readable text on this drawing."],
    svg: ["Find labels in this vector drawing."],
  };
  for (const text of examples[doc.format] || []) {
    const button = document.createElement("button");
    button.className = "suggestion";
    button.textContent = `↳ ${text}`;
    button.addEventListener("click", () => {
      $("question-input").value = text;
      $("question-input").focus();
    });
    suggestions.append(button);
  }
}

async function renderPreview() {
  const token = ++state.renderToken;
  const doc = state.selected;
  $("preview-message").hidden = true;
  $("empty-canvas").hidden = true;
  $("canvas-content").hidden = true;
  $("canvas-badge").hidden = true;
  $("canvas-legend").hidden = true;
  $("canvas-hint").hidden = true;
  $("canvas-status").textContent = "Loading source preview…";
  if (!doc) return;
  const format = state.previewFormat;
  if (!["pdf", "png", "jpg", "jpeg", "svg", "dxf"].includes(format)) {
    showPreviewMessage(`A faithful 2D preview is not implemented for ${format.toUpperCase()}. The selected file is still available to the supported structured tools.`);
    return;
  }
  try {
    const response = await api(`/api/documents/${state.previewId}/preview?page=${state.page}`);
    const blob = await response.blob();
    if (token !== state.renderToken) return;
    const contentType = response.headers.get("content-type") || "";
    if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
    state.objectUrl = URL.createObjectURL(blob);
    state.pageCount = Number(response.headers.get("x-page-count") || doc.page_count || 1);
    state.pageWidth = Number(response.headers.get("x-page-width") || 0);
    state.pageHeight = Number(response.headers.get("x-page-height") || 0);
    const viewBoxHeader = response.headers.get("x-page-viewbox");
    state.pageViewBox = viewBoxHeader
      ? viewBoxHeader.split(",").map(Number)
      : null;
    $("page-count").textContent = String(state.pageCount);
    $("page-input").value = String(state.page);
    $("page-input").max = String(state.pageCount);
    $("canvas-content").hidden = false;
    $("canvas-badge").hidden = false;
    $("canvas-legend").hidden = false;
    $("canvas-hint").hidden = false;
    $("canvas-status").textContent = doc.preview_relationship === "source document"
      ? `Original source · page ${state.page} of ${state.pageCount}`
      : `Faithful companion rendering · ${doc.preview_relationship}`;
    if (contentType.includes("svg") && !state.pageWidth) {
      image.addEventListener("load", setSvgSize, { once: true });
    }
    image.onload = () => {
      if (!state.pageWidth) {
        state.pageWidth = image.naturalWidth;
        state.pageHeight = image.naturalHeight;
      }
      updateOverlayViewBox();
      fitView();
      drawOverlays();
    };
    image.onerror = () => showPreviewMessage("The preview could not be decoded by the browser.");
    image.src = state.objectUrl;
  } catch (error) {
    showPreviewMessage(error.message);
  }
}

function setSvgSize() {
  if (!image.naturalWidth) return;
  state.pageWidth = image.naturalWidth;
  state.pageHeight = image.naturalHeight;
  updateOverlayViewBox();
}

function showPreviewMessage(message) {
  $("canvas-content").hidden = true;
  $("empty-canvas").hidden = true;
  $("preview-message").hidden = false;
  $("preview-message").textContent = message;
  $("canvas-status").textContent = "Preview unavailable";
  $("canvas-legend").hidden = true;
  $("canvas-hint").hidden = true;
}

function updateOverlayViewBox() {
  const width = state.pageWidth || image.naturalWidth || 1;
  const height = state.pageHeight || image.naturalHeight || 1;
  const [x, y, viewWidth, viewHeight] = state.pageViewBox || [0, 0, width, height];
  evidenceLayer.setAttribute("viewBox", `${x} ${y} ${viewWidth} ${viewHeight}`);
  evidenceLayer.setAttribute("preserveAspectRatio", "none");
}

function fitView() {
  if (!image.naturalWidth || !image.naturalHeight) return;
  const stage = $("canvas-stage");
  const availableWidth = Math.max(100, stage.clientWidth - 68);
  const availableHeight = Math.max(100, stage.clientHeight - 80);
  const nativeWidth = image.naturalWidth;
  const nativeHeight = image.naturalHeight;
  const fitScale = Math.min(availableWidth / nativeWidth, availableHeight / nativeHeight, 1.25);
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  state.zoom = Math.max(.08, fitScale * Math.min(dpr, 1));
  state.panX = 0;
  state.panY = 0;
  applyTransform();
  $("zoom-label").textContent = `${Math.round(state.zoom * 100)}%`;
}

function applyTransform() {
  imageStack.style.transform = `translate(calc(-50% + ${state.panX}px), calc(-50% + ${state.panY}px)) scale(${state.zoom})`;
  $("zoom-label").textContent = `${Math.round(state.zoom * 100)}%`;
}

function drawOverlays() {
  evidenceLayer.replaceChildren();
  if (!$("evidence-toggle").checked) return;
  for (const overlay of state.overlays) {
    if (overlay.page_or_view_id && Number(overlay.page_or_view_id) !== state.page) continue;
    if (["instance_mask", "semantic_mask"].includes(overlay.overlay_type) && overlay.geometry?.polygons) {
      for (const polygon of overlay.geometry.polygons) {
        const points = polygon
          .map((point) => point.map(Number))
          .filter((point) => point.length === 2 && point.every(Number.isFinite));
        if (points.length < 3) continue;
        const shape = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
        shape.setAttribute("points", points.map((point) => point.join(",")).join(" "));
        shape.setAttribute("class", "vision-mask");
        shape.setAttribute("fill-opacity", String(overlay.geometry.opacity || 0.24));
        shape.setAttribute("data-overlay-id", overlay.overlay_id);
        const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
        title.textContent = overlay.label;
        shape.append(title);
        evidenceLayer.append(shape);
      }
      continue;
    }
    if (["polygon", "polyline"].includes(overlay.overlay_type) && overlay.geometry?.points) {
      const points = overlay.geometry.points
        .map((point) => point.map(Number))
        .filter((point) => point.length === 2 && point.every(Number.isFinite));
      if (points.length < 2) continue;
      const closed = overlay.overlay_type === "polygon" || overlay.geometry.closed;
      const shape = document.createElementNS(
        "http://www.w3.org/2000/svg",
        closed ? "polygon" : "polyline",
      );
      shape.setAttribute("points", points.map((point) => point.join(",")).join(" "));
      shape.setAttribute("class", overlay.is_model_output ? "cad-outline model-evidence-highlight" : "cad-outline");
      shape.setAttribute("data-overlay-id", overlay.overlay_id);
      evidenceLayer.append(shape);
      continue;
    }
    if (overlay.overlay_type === "point" && overlay.geometry?.point) {
      const point = overlay.geometry.point.map(Number);
      if (point.length !== 2 || point.some((value) => !Number.isFinite(value))) continue;
      const marker = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      marker.setAttribute("cx", String(point[0]));
      marker.setAttribute("cy", String(point[1]));
      marker.setAttribute("r", "5");
      marker.setAttribute("class", "evidence-point");
      marker.setAttribute("data-overlay-id", overlay.overlay_id);
      evidenceLayer.append(marker);
      continue;
    }
    if (!["text_region", "bounding_box"].includes(overlay.overlay_type) || !overlay.geometry?.bbox) continue;
    const bbox = overlay.geometry.bbox.map(Number);
    if (bbox.length !== 4 || bbox.some((value) => !Number.isFinite(value))) continue;
    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("x", String(bbox[0]));
    rect.setAttribute("y", String(bbox[1]));
    rect.setAttribute("width", String(Math.max(0, bbox[2] - bbox[0])));
    rect.setAttribute("height", String(Math.max(0, bbox[3] - bbox[1])));
    rect.setAttribute("class", overlay.is_model_output ? "evidence-highlight model-evidence-highlight" : "evidence-highlight");
    rect.setAttribute("data-overlay-id", overlay.overlay_id);
    evidenceLayer.append(rect);
  }
}

function setActiveEvidence(evidence, overlays) {
  state.activeEvidence = evidence;
  state.overlays = overlays || [];
  if (evidence.page && evidence.page !== state.page && state.previewFormat === "pdf") {
    state.page = evidence.page;
    renderPreview();
    return;
  }
  drawOverlays();
  const point = evidence.geometry?.rendered_point || evidence.geometry?.point;
  const polygonPoints = evidence.geometry?.rendered_points;
  const focusBox = evidence.bbox || (polygonPoints?.length
    ? [
      Math.min(...polygonPoints.map((entry) => entry[0])),
      Math.min(...polygonPoints.map((entry) => entry[1])),
      Math.max(...polygonPoints.map((entry) => entry[0])),
      Math.max(...polygonPoints.map((entry) => entry[1])),
    ]
    : point ? [point[0] - 12, point[1] - 12, point[0] + 12, point[1] + 12] : null);
  if (focusBox && state.pageWidth) {
    const [x0, y0, x1, y1] = focusBox.map(Number);
    const boxWidth = x1 - x0;
    const boxHeight = y1 - y0;
    const stage = $("canvas-stage");
    const frame = state.pageViewBox || [0, 0, state.pageWidth, state.pageHeight];
    const scaleX = image.naturalWidth / frame[2];
    const scaleY = image.naturalHeight / frame[3];
    const displayWidth = boxWidth * scaleX;
    const displayHeight = boxHeight * scaleY;
    const fitScale = Math.min((stage.clientWidth * .65) / displayWidth, (stage.clientHeight * .65) / displayHeight, 3.2);
    const centerX = (x0 + x1) / 2;
    const centerY = (y0 + y1) / 2;
    state.zoom = Math.max(state.zoom, fitScale);
    state.panX = -((centerX - frame[0]) * scaleX - image.naturalWidth / 2) * state.zoom;
    state.panY = -((centerY - frame[1]) * scaleY - image.naturalHeight / 2) * state.zoom;
    applyTransform();
  }
}

function evidenceKind(ref) {
  const method = ref.extraction_method?.toLowerCase() || "";
  if (/grounding dino|sam 2|cubicasa|multimodal llm/.test(method)) return "Vision-model evidence";
  if (ref.entity_type === "svg_text") return "Native SVG text";
  if (ref.entity_id || ["ifc_model_coordinates", "dxf_model_units"].includes(ref.coordinate_system)) return "IFC / CAD entity";
  if (ref.coordinate_system === "image_pixels" && ref.entity_type) return "Vision-model evidence";
  if (ref.entity_type) return "Source entity";
  if (ref.coordinate_system === "pdf_points") return "Selectable PDF text";
  if (ref.coordinate_system === "image_pixels") return "Image region";
  return "Source evidence";
}

function renderAnswer(result) {
  const area = $("answer-area");
  area.replaceChildren();
  const stateBox = document.createElement("div");
  stateBox.className = `answer-state status-${result.status}`;
  const meta = document.createElement("div");
  meta.className = "answer-meta";
  const status = document.createElement("span");
  status.className = "answer-status";
  const dot = document.createElement("i");
  const statusText = document.createElement("span");
  statusText.textContent = result.status;
  status.append(dot, statusText);
  const route = document.createElement("span");
  route.textContent = result.question_spec?.operation || "analysis";
  meta.append(status, route);
  const answer = document.createElement("p");
  answer.className = "answer-text";
  answer.textContent = result.answer || "No answer returned";
  stateBox.append(meta, answer);
  if (result.value !== null && result.value !== undefined && typeof result.value !== "string") {
    const value = document.createElement("div");
    value.className = "answer-value";
    value.textContent = `${result.value}${result.unit ? ` ${result.unit}` : ""}`;
    stateBox.append(value);
  }
  if (result.calculation?.length) {
    const calculation = document.createElement("div");
    calculation.className = "answer-calculation";
    const heading = document.createElement("strong");
    heading.textContent = "Calculation";
    const steps = document.createElement("ul");
    for (const step of result.calculation) {
      const item = document.createElement("li");
      item.textContent = step;
      steps.append(item);
    }
    calculation.append(heading, steps);
    stateBox.append(calculation);
  }
  const validation = document.createElement("div");
  validation.className = "answer-validation";
  validation.textContent = result.validation || "No validation summary returned.";
  stateBox.append(validation);
  if (result.assumptions?.length) {
    const assumptions = document.createElement("div");
    assumptions.className = "answer-validation";
    assumptions.textContent = `Method: ${result.assumptions.join(" ")}`;
    stateBox.append(assumptions);
  }
  if (result.warnings?.length) {
    const warnings = document.createElement("ul");
    warnings.className = "answer-warnings";
    for (const text of result.warnings) {
      const item = document.createElement("li");
      item.textContent = text;
      warnings.append(item);
    }
    stateBox.append(warnings);
  }
  area.append(stateBox);

  if (result.evidence?.length) {
    const title = document.createElement("div");
    title.className = "subsection-title";
    const label = document.createElement("span");
    label.textContent = "SUPPORTING EVIDENCE";
    const count = document.createElement("span");
    count.className = "evidence-count";
    count.textContent = `${result.evidence.length} reference${result.evidence.length === 1 ? "" : "s"}`;
    title.append(label, count);
    area.append(title);
    result.evidence.slice(0, 10).forEach((ref, index) => {
      const card = document.createElement("button");
      card.className = "evidence-card";
      const top = document.createElement("span");
      top.className = "evidence-card-top";
      const kind = document.createElement("span");
      kind.className = "evidence-type";
      kind.textContent = evidenceKind(ref);
      const page = document.createElement("span");
      page.textContent = ref.page ? `PAGE ${ref.page}` : (ref.entity_id || "SOURCE");
      top.append(kind, page);
      const quote = document.createElement("span");
      quote.className = "evidence-quote";
      quote.textContent = ref.extracted_content || `${ref.entity_type || "Entity"} ${ref.entity_id || ""}`;
      const sub = document.createElement("span");
      sub.className = "evidence-sub";
      const hasLocation = ref.bbox || ref.geometry?.rendered_point || ref.geometry?.point || ref.geometry?.rendered_points;
      sub.textContent = `${displayName(ref.path)}${hasLocation ? " · click to locate source evidence" : " · no 2D projection available"}`;
      card.append(top, quote, sub);
      card.addEventListener("click", () => {
        const samePage = result.overlays?.filter((overlay) => overlay.page_or_view_id === String(ref.page)) || result.overlays || [];
        setActiveEvidence(ref, samePage);
        $("canvas-status").textContent = hasLocation
          ? `Evidence highlighted · page ${ref.page}`
          : `Entity evidence · ${ref.entity_id || "source reference"} · 2D projection unavailable`;
      });
      area.append(card);
    });
  }

  if (result.trace?.length) {
    const details = document.createElement("details");
    details.className = "trace-details";
    const summary = document.createElement("summary");
    summary.textContent = `EXECUTION TRACE · ${result.trace.length} steps`;
    details.append(summary);
    for (const step of result.trace) {
      const row = document.createElement("div");
      row.className = "trace-step";
      const indicator = document.createElement("i");
      indicator.className = `trace-indicator ${step.status === "failed" ? "failed" : step.status === "skipped" ? "skipped" : ""}`;
      const copy = document.createElement("span");
      const name = document.createElement("span");
      name.className = "trace-name";
      name.textContent = step.tool_name;
      const description = document.createElement("span");
      description.className = "trace-summary";
      description.textContent = step.summary;
      copy.append(name, description);
      const evidenceCount = document.createElement("span");
      evidenceCount.className = "trace-count";
      evidenceCount.textContent = step.evidence_count ? `${step.evidence_count} ev.` : step.status;
      row.append(indicator, copy, evidenceCount);
      details.append(row);
    }
    area.append(details);
  }
}

async function askQuestion() {
  if (!state.selected) {
    showToast("Select a document first.");
    return;
  }
  const question = $("question-input").value.trim();
  if (question.length < 3) {
    showToast("Enter a question with at least three characters.");
    return;
  }
  const button = $("ask-button");
  button.disabled = true;
  button.querySelector("span").textContent = "Working…";
  $("canvas-status").textContent = state.llmConfig
    ? `Routing with ${state.llmConfig.model} and available document tools…`
    : "Planning and checking local document evidence…";
  try {
    const requestBody = {
      document_id: state.selected.document_id,
      question,
    };
    if (state.previewFormat === "pdf") requestBody.page_number = state.page;
    if (state.llmConfig) requestBody.llm = state.llmConfig;
    requestBody.gemini_vl_consent = state.geminiVisionConsent;
    const response = await api("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody),
    });
    const result = await response.json();
    renderAnswer(result);
    state.overlays = result.overlays || [];
    drawOverlays();
    $("canvas-status").textContent = result.status === "supported"
      ? `Evidence-backed result · ${result.evidence.length} source references`
      : result.status === "error"
        ? "Analysis failed"
        : `Analysis complete · ${result.status}`;
    if (result.status === "error") {
      showToast(result.validation || result.answer || "Analysis failed.");
    }
  } catch (error) {
    showToast(`Analysis failed: ${error.message}`);
    $("canvas-status").textContent = "Analysis failed";
  } finally {
    button.disabled = false;
    button.querySelector("span").textContent = "Analyze";
  }
}

async function openLLMSettings() {
  $("llm-model").value = state.llmConfig?.model || "";
  $("llm-remote-consent").checked = Boolean(state.llmConfig);
  $("gemini-vl-remote-consent").checked = state.geminiVisionConsent;
  $("llm-config-status").textContent = state.llmConfig
    ? `Configured for this tab: ${state.llmConfig.model}. Credentials are held in memory only.`
    : "Groq is optional for planning. Specialist models process drawings locally when installed.";
  $("llm-modal").hidden = false;
  try {
    const response = await api("/api/llm/status");
    const configStatus = await response.json();
    state.groqModel = configStatus.model || null;
    state.geminiVlConfigured = Boolean(configStatus.gemini_vl_configured);
    state.geminiVlModel = configStatus.gemini_vl_model || null;
    $("gemini-vl-remote-consent").disabled = !state.geminiVlConfigured;
    if (!state.llmConfig && state.groqModel) $("llm-model").value = state.groqModel;
    $("llm-model").readOnly = Boolean(state.groqModel);
    $("llm-config-status").textContent = configStatus.api_key_configured
      ? (state.groqModel
        ? `Backend Groq is configured for ${state.groqModel}. Confirm consent to use it.`
        : "GROQ_API_KEY is configured, but GROQ_MODEL is not. Enter a model or set GROQ_MODEL.")
      : "Groq key not detected. Set GROQ_API_KEY in the ignored .env file or hosting secrets.";
    $("llm-config-status").textContent += state.geminiVlConfigured
      ? ` Gemini free-tier semantic review is configured as ${state.geminiVlModel}; per-request image consent is required. Google may review or use free-tier content to improve products. Do not send confidential drawings.`
      : ` Gemini semantic review is unavailable${configStatus.gemini_vl_model_error ? `: ${configStatus.gemini_vl_model_error}` : "; set GEMINI_API_KEY in the backend environment"}.`;
  } catch (error) {
    $("llm-config-status").textContent = `Could not check backend provider setup: ${error.message}`;
  }
}

async function saveLLMSettings() {
  const model = state.groqModel || $("llm-model").value.trim();
  if (!model) {
    showToast("Enter a model name or configure GROQ_MODEL in the backend.");
    return;
  }
  if (!$("llm-remote-consent").checked) {
    showToast("Confirm the provider data-sharing notice before using an external LLM.");
    return;
  }
  const saveButton = $("llm-save");
  saveButton.disabled = true;
  try {
    const response = await api("/api/llm/status");
    const configStatus = await response.json();
    if (!configStatus.api_key_configured) {
      const message = "Groq isn't configured on the backend. Set GROQ_API_KEY in the ignored .env file or hosting secrets, then restart the app.";
      $("llm-config-status").textContent = message;
      showToast(message);
      return;
    }
    const selectedModel = configStatus.model || model;
    state.groqModel = configStatus.model || null;
    state.llmConfig = { provider: "groq", model: selectedModel };
    $("llm-config-status").textContent = `Groq is selected for question interpretation and tool routing only: ${selectedModel}.`;
    $("llm-settings-button").textContent = "LLM ready";
    $("llm-modal").hidden = true;
    showToast(`Using Groq ${selectedModel} for planning only.`);
  } catch (error) {
    const message = `Could not verify backend Groq setup: ${error.message}`;
    $("llm-config-status").textContent = message;
    showToast(message);
  } finally {
    saveButton.disabled = false;
  }
}

function clearLLMSettings() {
  state.llmConfig = null;
  $("llm-model").value = "";
  $("llm-remote-consent").checked = false;
  $("gemini-vl-remote-consent").checked = false;
  state.geminiVisionConsent = false;
  $("llm-config-status").textContent = "Groq planning and Gemini image-sharing consent cleared; local tools stay local.";
  $("llm-settings-button").textContent = "LLM setup";
  $("llm-modal").hidden = true;
  showToast("External model consent cleared from this tab.");
}

async function loadLicense() {
  if (!state.selected) return;
  try {
    const response = await api(`/api/documents/${state.selected.document_id}/license`);
    state.licenseText = await response.json();
  } catch {
    state.licenseText = null;
  }
}

function openLicense() {
  if (!state.licenseText) {
    showToast("Licence metadata is unavailable for this document.");
    return;
  }
  $("modal-credit").textContent = state.licenseText.credit || "Source-specific attribution is listed in the dataset licence file.";
  $("modal-license").textContent = state.licenseText.text || "No licence text available.";
  $("modal").hidden = false;
}

async function uploadFile(file) {
  if (!file) return;
  try {
    const response = await api("/api/upload", {
      method: "POST",
      headers: { "X-Filename": file.name, "Content-Type": file.type || "application/octet-stream" },
      body: file,
    });
    const uploaded = await response.json();
    state.documents.push(uploaded);
    populateSources();
    renderDocumentList();
    await selectDocument(uploaded.document_id);
    showToast("Document added to the local workspace.");
  } catch (error) {
    showToast(`Upload failed: ${error.message}`);
  } finally {
    $("upload-input").value = "";
  }
}

function movePage(delta) {
  const page = Math.max(1, Math.min(state.pageCount, state.page + delta));
  if (page !== state.page) {
    state.page = page;
    state.overlays = state.overlays.filter((overlay) => Number(overlay.page_or_view_id) === page);
    renderPreview();
  }
}

function attachEvents() {
  $("document-search").addEventListener("input", renderDocumentList);
  $("source-filter").addEventListener("change", renderDocumentList);
  $("refresh-documents").addEventListener("click", loadDocuments);
  $("ask-button").addEventListener("click", askQuestion);
  $("question-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) askQuestion();
  });
  $("upload-input").addEventListener("change", (event) => uploadFile(event.target.files?.[0]));
  $("previous-page").addEventListener("click", () => movePage(-1));
  $("next-page").addEventListener("click", () => movePage(1));
  $("page-input").addEventListener("change", () => {
    const number = Number($("page-input").value);
    if (Number.isInteger(number) && number >= 1 && number <= state.pageCount) {
      state.page = number;
      renderPreview();
    }
  });
  $("zoom-in").addEventListener("click", () => { state.zoom = Math.min(5, state.zoom * 1.2); applyTransform(); });
  $("zoom-out").addEventListener("click", () => { state.zoom = Math.max(.1, state.zoom / 1.2); applyTransform(); });
  $("fit-view").addEventListener("click", fitView);
  $("evidence-toggle").addEventListener("change", drawOverlays);
  $("source-toggle").addEventListener("change", () => { image.style.visibility = $("source-toggle").checked ? "visible" : "hidden"; });
  $("canvas-stage").addEventListener("wheel", (event) => {
    if (!image.naturalWidth) return;
    event.preventDefault();
    state.zoom = Math.max(.08, Math.min(5, state.zoom * (event.deltaY < 0 ? 1.1 : .9)));
    applyTransform();
  }, { passive: false });
  $("canvas-stage").addEventListener("pointerdown", (event) => {
    if (event.target.closest(".canvas-legend")) return;
    dragging = true;
    dragOrigin = { x: event.clientX - state.panX, y: event.clientY - state.panY };
    $("canvas-stage").setPointerCapture(event.pointerId);
  });
  $("canvas-stage").addEventListener("pointermove", (event) => {
    if (!dragging || !dragOrigin) return;
    state.panX = event.clientX - dragOrigin.x;
    state.panY = event.clientY - dragOrigin.y;
    applyTransform();
  });
  $("canvas-stage").addEventListener("pointerup", () => { dragging = false; dragOrigin = null; });
  $("license-button").addEventListener("click", openLicense);
  $("about-button").addEventListener("click", () => showToast("Local-first demo · unsupported analysis is reported rather than fabricated."));
  $("modal-close").addEventListener("click", () => { $("modal").hidden = true; });
  $("modal-backdrop").addEventListener("click", () => { $("modal").hidden = true; });
  $("llm-settings-button").addEventListener("click", openLLMSettings);
  $("llm-save").addEventListener("click", saveLLMSettings);
  $("llm-clear").addEventListener("click", clearLLMSettings);
  $("gemini-vl-remote-consent").addEventListener("change", (event) => {
    state.geminiVisionConsent = Boolean(event.target.checked && state.geminiVlConfigured);
  });
  $("llm-modal-close").addEventListener("click", () => { $("llm-modal").hidden = true; });
  $("llm-modal-backdrop").addEventListener("click", () => { $("llm-modal").hidden = true; });
  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      $("document-search").focus();
    }
    if (event.key === "Escape") {
      $("modal").hidden = true;
      $("llm-modal").hidden = true;
    }
  });
  window.addEventListener("resize", () => { if (image.naturalWidth) fitView(); });
}

async function loadTools() {
  try {
    const response = await api("/api/tools");
    const tools = await response.json();
    const available = tools.filter((tool) => tool.available).length;
    $("tool-count").textContent = `${available} tool${available === 1 ? "" : "s"}`;
  } catch {
    $("tool-count").textContent = "offline";
  }
}

attachEvents();
loadTools();
loadDocuments();
