import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  Activity,
  AlertCircle,
  ArrowDownRight,
  ArrowUpRight,
  Box,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Crosshair,
  FileImage,
  FileText,
  DraftingCompass,
  LoaderCircle,
  Maximize2,
  Menu,
  MessageSquareText,
  MousePointer2,
  Plus,
  RotateCcw,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  Upload,
  X,
} from "lucide-react";
import { api } from "./api";
import type {
  Answer,
  DocumentRecord,
  EvidenceOverlay,
  EvidenceRef,
  SceneElement,
  SceneResponse,
} from "./types";

const SceneViewport = lazy(() =>
  import("./SceneViewport").then((module) => ({ default: module.SceneViewport })),
);

type ViewMode = "split" | "drawing" | "model";
type Preview = {
  url: string;
  width: number;
  height: number;
  pageCount: number;
  viewBox: [number, number, number, number] | null;
  coordinateSystem: string;
};

function documentName(path: string): string {
  return path.split("/").pop() || path;
}

function fileSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fileLabel(format: string): string {
  return format.toUpperCase().replace("JPEG", "JPG").slice(0, 5);
}

function sceneCapable(format: string): boolean {
  return ["pdf", "png", "jpg", "jpeg"].includes(format.toLowerCase());
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function numericArray(value: unknown): number[] | null {
  if (!Array.isArray(value) || !value.every((item) => typeof item === "number")) {
    return null;
  }
  return value;
}

function polygonLists(value: unknown): number[][][] {
  if (!Array.isArray(value)) return [];
  const candidates = Array.isArray(value[0]?.[0]) ? value as unknown[] : [value];
  return candidates.flatMap((candidate) => {
    if (!Array.isArray(candidate)) return [];
    const points = candidate.filter(
      (point): point is number[] =>
        Array.isArray(point) &&
        point.length >= 2 &&
        typeof point[0] === "number" &&
        typeof point[1] === "number",
    );
    return points.length >= 3 ? [points] : [];
  });
}

function boxForOverlay(overlay: EvidenceOverlay): number[] | null {
  const geometry = overlay.geometry;
  if (Array.isArray(geometry)) return numericArray(geometry);
  return isRecord(geometry) ? numericArray(geometry.bbox) : null;
}

function polygonsForOverlay(overlay: EvidenceOverlay): number[][][] {
  if (!isRecord(overlay.geometry)) return [];
  return polygonLists(overlay.geometry.polygons ?? overlay.geometry.points);
}

function sourceRegionForElement(element: SceneElement): number[] | null {
  const region = element.provenance.source_region;
  return Array.isArray(region) && region.length >= 4 && region.every((value) => typeof value === "number")
    ? region.slice(0, 4)
    : null;
}

function sameBoundingBox(left: number[] | null | undefined, right: number[] | null | undefined): boolean {
  return Boolean(
    left &&
    right &&
    left.length >= 4 &&
    right.length >= 4 &&
    left.slice(0, 4).every((value, index) => Math.abs(value - right[index]) < 0.5),
  );
}

function App() {
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [selected, setSelected] = useState<DocumentRecord | null>(null);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [previewNote, setPreviewNote] = useState("Select a drawing to begin.");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [zoomOrigin, setZoomOrigin] = useState("center");
  const [search, setSearch] = useState("");
  const [viewMode, setViewMode] = useState<ViewMode>("split");
  const [scene, setScene] = useState<SceneResponse | null>(null);
  const [sceneLoading, setSceneLoading] = useState(false);
  const [sceneError, setSceneError] = useState("");
  const [sceneOffset, setSceneOffset] = useState(0);
  const [selectedElement, setSelectedElement] = useState<SceneElement | null>(null);
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string | null>(null);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState("");
  const allowGroq = false;
  const allowGemini = false;
  const evidenceGroupRefs = useRef<Record<string, SVGGElement | null>>({});
  const focusTimerRef = useRef<number | null>(null);
  const groqModel = "";
  const [uploading, setUploading] = useState(false);
  const [listError, setListError] = useState("");
  const [assistantOpen, setAssistantOpen] = useState(true);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const selectionToken = useRef(0);
  const pageToken = useRef(0);
  const selectedDocumentId = useRef<string | null>(null);
  const uploadInput = useRef<HTMLInputElement>(null);

  const filteredDocuments = useMemo(() => {
    const query = search.trim().toLowerCase();
    const matches = documents.filter((document) =>
      !query ||
      document.path.toLowerCase().includes(query) ||
      document.format.toLowerCase().includes(query),
    );
    const visible = matches.slice(0, 250);
    if (selected && matches.some((item) => item.document_id === selected.document_id) &&
      !visible.some((item) => item.document_id === selected.document_id)) {
      visible[visible.length - 1] = selected;
    }
    return visible;
  }, [documents, search, selected]);

  const demoPrompts = useMemo(() => {
    if (!selected) return [];
    const format = selected.format.toLowerCase();
    if (format === "ifc") {
      return [
        ["Native IFC count", "How many doors are in this model?"],
        ["Scoped BIM count", "How many windows are on Level 1?"],
      ] as const;
    }
    if (format === "dxf") {
      return [
        ["Room geometry", "What is the total area of the rooms in square meters?"],
        ["Door geometry", "How many doors are shown on this drawing?"],
      ] as const;
    }
    if (format === "pdf") {
      return [["Source text", "Find readable text and show its source evidence."]] as const;
    }
    return [
      ["Local vision", "How many doors are shown on this floor plan?"],
      ["OCR evidence", "Find readable text on this drawing."],
    ] as const;
  }, [selected]);

  const questionIntents = useMemo(() => [
    ["Quantities", "How many doors, windows, or rooms are shown?"],
    ["Locations", "Where is the stair or entrance located?"],
    ["Dimensions", "What is the area or length of this space?"],
    ["Text & notes", "What readable Finnish notes are on this drawing?"],
    ["Levels & BIM", "How many floors and elements are in the model?"],
  ] as const, [selected]);

  useEffect(() => {
    if (preview?.url) return () => URL.revokeObjectURL(preview.url);
  }, [preview]);

  const refreshDocuments = useCallback(async () => {
    setListError("");
    try {
      const items = await api.documents();
      setDocuments(items);
      if (!selectedDocumentId.current) {
        const preferred = items.find(
          (document) =>
            document.format === "ifc" &&
            document.path.toLowerCase().includes("esplanades"),
        ) || items.find((document) => document.format === "ifc") ||
          items.find((document) => ["pdf", "png", "jpg"].includes(document.format)) ||
          items[0];
        if (preferred) void chooseDocument(preferred);
      }
    } catch (error) {
      setListError(error instanceof Error ? error.message : "The document catalog could not be loaded.");
    }
  }, []);

  useEffect(() => {
    void refreshDocuments();
  }, [refreshDocuments]);

  const chooseDocument = useCallback(async (document: DocumentRecord) => {
    const token = ++selectionToken.current;
    if (focusTimerRef.current !== null) {
      window.clearTimeout(focusTimerRef.current);
      focusTimerRef.current = null;
    }
    pageToken.current += 1;
    setLibraryOpen(false);
    selectedDocumentId.current = document.document_id;
    setSelected(document);
    setPreview(null);
    setPreviewId(document.document_id);
    setPreviewNote("Loading source preview…");
    setPage(1);
    setZoom(1);
    setScene(null);
    setSceneLoading(false);
    setSceneError("");
    setSceneOffset(0);
    setSelectedElement(null);
    setSelectedEvidenceId(null);
    setAnswer(null);
    setAskError("");
    setAsking(false);

    try {
      const detail = await api.document(document.document_id);
      if (token !== selectionToken.current) return;
      selectedDocumentId.current = detail.document_id;
      setSelected(detail);
      const id = detail.preview_document_id || detail.document_id;
      setPreviewId(id);
      setPreviewNote("Rendering the original source…");
      try {
        const rendered = await api.preview(id, 1);
        if (token !== selectionToken.current) {
          URL.revokeObjectURL(rendered.url);
          return;
        }
        setPreview({
          ...rendered,
          viewBox: rendered.viewBox
            ? rendered.viewBox.split(",").map(Number) as [number, number, number, number]
            : null,
        });
        setPreviewNote("");
      } catch (error) {
        if (token === selectionToken.current) {
          setPreviewNote(error instanceof Error ? error.message : "A faithful 2D preview is unavailable.");
        }
      }
    } catch (error) {
      if (token === selectionToken.current) {
        setPreviewNote(error instanceof Error ? error.message : "Document details could not be loaded.");
      }
    }

    if (document.format === "ifc") {
      setSceneLoading(true);
      try {
        const result = await api.scene(document.document_id, 150);
        if (token === selectionToken.current) {
          setScene(result);
          setSceneError(result.status === "unavailable" ? result.warnings.join(" ") : "");
          // Do not keep the first useful model view behind the full-model
          // tessellation. Remaining pages are merged in the background.
          setSceneLoading(false);
          // Render the first native IFC page immediately, then merge the
          // remaining pages so multi-storey models are not mistaken for one
          // floor. The API keeps each request bounded for responsiveness.
          let combined = result;
          let nextOffset = result.offset + result.elements.length;
          while (combined.has_more && token === selectionToken.current) {
            const nextPage = await api.scene(document.document_id, 400, nextOffset);
            if (token !== selectionToken.current) return;
            combined = {
              ...combined,
              elements: [...combined.elements, ...nextPage.elements],
              has_more: nextPage.has_more,
            };
            nextOffset += nextPage.elements.length;
            setSceneOffset(nextOffset);
            setScene(combined);
          }
        }
      } catch (error) {
        if (token === selectionToken.current) {
          setSceneError(error instanceof Error ? error.message : "IFC scene loading failed.");
        }
      } finally {
        if (token === selectionToken.current) setSceneLoading(false);
      }
    }
  }, []);

  const loadPage = useCallback(async (nextPage: number) => {
    if (!previewId || !selected) return;
    const safePage = Math.max(1, Math.min(preview?.pageCount || 1, nextPage));
    const token = ++pageToken.current;
    setPage(safePage);
    try {
      const rendered = await api.preview(previewId, safePage);
      if (token !== pageToken.current) {
        URL.revokeObjectURL(rendered.url);
        return;
      }
      setPreview({
        ...rendered,
        viewBox: rendered.viewBox
          ? rendered.viewBox.split(",").map(Number) as [number, number, number, number]
          : null,
      });
    } catch (error) {
      setPreviewNote(error instanceof Error ? error.message : "Page rendering failed.");
    }
  }, [preview?.pageCount, previewId, selected]);

  const generateScene = useCallback(async () => {
    if (!selected || !sceneCapable(selected.format)) return;
    const token = selectionToken.current;
    setSceneLoading(true);
    setSceneError("");
    setScene(null);
    try {
      const result = await api.scene(selected.document_id, 400);
      if (token !== selectionToken.current) return;
      setScene(result);
      if (result.status === "unavailable") setSceneError(result.warnings.join(" "));
    } catch (error) {
      if (token === selectionToken.current) {
        setSceneError(error instanceof Error ? error.message : "Spatial reconstruction failed.");
      }
    } finally {
      if (token === selectionToken.current) setSceneLoading(false);
    }
  }, [selected]);

  const onUpload = useCallback(async (file?: File) => {
    if (!file) return;
    setUploading(true);
    setListError("");
    try {
      const uploaded = await api.upload(file);
      const items = await api.documents();
      setDocuments(items);
      await chooseDocument(uploaded);
    } catch (error) {
      setListError(error instanceof Error ? error.message : "The file could not be uploaded.");
    } finally {
      setUploading(false);
      if (uploadInput.current) uploadInput.current.value = "";
    }
  }, [chooseDocument]);

  const selectElement = useCallback((element: SceneElement | null) => {
    setSelectedElement(element);
    setSelectedEvidenceId(element?.global_id || element?.id || null);
  }, []);

  const selectEvidence = useCallback((id: string | null) => {
    setSelectedEvidenceId(id);
    const element = scene?.elements.find(
      (item) => item.global_id === id || item.id === id,
    );
    if (element) setSelectedElement(element);
  }, [scene]);

  const focusEvidence = useCallback((evidence: EvidenceRef) => {
    if (focusTimerRef.current !== null) {
      window.clearTimeout(focusTimerRef.current);
      focusTimerRef.current = null;
    }
    const matchingOverlay = answer?.overlays.find((overlay) =>
      (evidence.entity_id && overlay.entity_id === evidence.entity_id) ||
      (overlay.document_id === evidence.document_id && sameBoundingBox(boxForOverlay(overlay), evidence.bbox)),
    );
    const targetId = matchingOverlay?.entity_id || matchingOverlay?.overlay_id || evidence.entity_id || null;
    selectEvidence(targetId);
    if (matchingOverlay) {
      const box = boxForOverlay(matchingOverlay) || evidence.bbox;
      if (box && preview && preview.width > 0 && preview.height > 0) {
        const centerX = ((box[0] + box[2]) / 2 / preview.width) * 100;
        const centerY = ((box[1] + box[3]) / 2 / preview.height) * 100;
        const boxWidth = Math.max(1, box[2] - box[0]);
        const boxHeight = Math.max(1, box[3] - box[1]);
        const focusZoom = Math.min(
          1.85,
          Math.max(1.15, Math.min(preview.width / boxWidth, preview.height / boxHeight) / 4.5),
        );
        // First return to a whole-drawing view, then animate into the new
        // evidence target. This makes changing evidence feel intentional
        // instead of jumping between unrelated regions.
        setZoomOrigin("center");
        setZoom(1);
        // Give the viewer time to see the complete drawing before moving to
        // the evidence. The CSS transition then performs the second, slow
        // camera-like move toward the highlighted region.
        focusTimerRef.current = window.setTimeout(() => {
          setZoomOrigin(`${centerX}% ${centerY}%`);
          setZoom(focusZoom);
          focusTimerRef.current = null;
        }, 520);
      }
      requestAnimationFrame(() => {
        evidenceGroupRefs.current[matchingOverlay.overlay_id]?.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" });
      });
    }
    const pageNumber = evidence.page;
    if (typeof pageNumber === "number" && pageNumber !== page) void loadPage(pageNumber);
  }, [answer, loadPage, page, preview, selectEvidence]);

  const askQuestion = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selected || !question.trim() || asking) return;
    if (allowGroq && !groqModel.trim()) {
      setAskError("Enter a Groq model name or set GROQ_MODEL before opting in.");
      return;
    }
    const token = selectionToken.current;
    setAsking(true);
    setAskError("");
    setAnswer(null);
    setSelectedEvidenceId(null);
    try {
      const result = await api.ask(
        selected.document_id,
        question.trim(),
        page,
        allowGroq,
        allowGemini,
        groqModel.trim(),
      );
      if (token !== selectionToken.current) return;
      setAnswer(result);
      const entityIds = [...new Set(
        result.evidence
          .map((item) => item.entity_id)
          .filter((id): id is string => Boolean(id && /^[A-Za-z0-9_$]{22}$/.test(id))),
      )];
      if (selected.format === "ifc" && entityIds.length) {
        try {
          const selection = await api.selectedElements(selected.document_id, entityIds.slice(0, 500));
          if (token !== selectionToken.current) return;
          setScene((current) => {
            if (!current) return selection;
            const merged = new Map(current.elements.map((element) => [element.id, element]));
            for (const element of selection.elements) merged.set(element.id, element);
            return { ...current, elements: [...merged.values()] };
          });
        } catch (error) {
          if (token !== selectionToken.current) return;
          setAskError(
            `Answer returned, but selected IFC evidence could not be loaded: ${
              error instanceof Error ? error.message : "unknown API error"
            }`,
          );
        }
      } else if (selected.format !== "ifc" && sceneCapable(selected.format) && !scene) {
        // After analysis, make the complete detected 2.5D overview available
        // without requiring a second manual action. This is an overview only;
        // evidence clicks still drive the focused inspection.
        void generateScene();
      }
    } catch (error) {
      if (token === selectionToken.current) {
        setAskError(error instanceof Error ? error.message : "Question processing failed.");
      }
    } finally {
      if (token === selectionToken.current) setAsking(false);
    }
  }, [allowGemini, allowGroq, asking, generateScene, groqModel, page, question, scene, selected]);

  const evidenceLayers = answer?.overlays.filter((overlay) =>
    overlay.document_id === selected?.document_id ||
    overlay.document_id === previewId,
  ) || [];
  const rasterOverview = scene?.coordinate_system === "source_pixels_display_only"
    ? scene.elements
      .map((element) => ({ element, box: sourceRegionForElement(element) }))
      .filter((item): item is { element: SceneElement; box: number[] } => Boolean(item.box))
    : [];

  return (
    <div className="workbench">
      <header className="topbar">
        <button className="icon-button mobile-menu" onClick={() => setLibraryOpen((open) => !open)} title="Open document library" aria-label="Toggle document library">
          <Menu size={17} />
        </button>
        <a className="brand" href="/" aria-label="BluePrintIQ home">
          <span className="brand-mark"><DraftingCompass size={17} strokeWidth={2.2} /></span>
          <span className="brand-copy">
            <strong>BluePrintIQ</strong>
            <small>CONSTRUCTION INTELLIGENCE</small>
          </span>
        </a>
        <div className="topbar-right">
          <span className="privacy-chip"><ShieldCheck size={13} /> Source-linked evidence</span>
          <button className="icon-link panel-toggle" onClick={() => setAssistantOpen((open) => !open)} title="Toggle question panel">
            <MessageSquareText size={15} /><span>{assistantOpen ? "Close panel" : "Ask"}</span>
          </button>
          <a className="icon-link" href="/api/health" target="_blank" rel="noreferrer" title="Backend health">
            <Activity size={16} /><span>System</span>
          </a>
        </div>
      </header>

      <main className={`layout ${assistantOpen ? "" : "assistant-collapsed"} ${libraryOpen ? "library-open" : ""}`}>
        <aside className="library-panel">
          <div className="panel-title-row">
            <div>
              <p className="eyebrow">PROJECT FILES</p>
              <h1>Documents <span className="count-chip">{documents.length}</span></h1>
            </div>
            <button className="icon-button" onClick={() => void refreshDocuments()} title="Refresh catalog" aria-label="Refresh catalog">
              <RotateCcw size={15} />
            </button>
          </div>
          <label className="search-field">
            <Search size={16} />
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Find a drawing or model…" />
            <kbd>⌘ K</kbd>
          </label>
          <div className="library-label">
            <span>LOCAL INDEX</span>
            <span>{filteredDocuments.length}{documents.length > filteredDocuments.length ? "+" : ""} FILES</span>
          </div>
          <div className="document-list" role="listbox" aria-label="Project documents">
            {filteredDocuments.map((document) => (
              <button
                type="button"
                role="option"
                aria-selected={document.document_id === selected?.document_id}
                className={`document-row ${document.document_id === selected?.document_id ? "active" : ""}`}
                key={document.document_id}
                onClick={() => void chooseDocument(document)}
              >
                <span className={`file-badge format-${document.format}`}>{fileLabel(document.format)}</span>
                <span className="document-copy">
                  <strong title={documentName(document.path)}>{documentName(document.path)}</strong>
                  <small>{document.source} <i>·</i> {fileSize(document.size_bytes)}</small>
                </span>
                {document.format === "ifc" && <Box className="document-type-icon" size={14} />}
              </button>
            ))}
            {!filteredDocuments.length && (
              <div className="list-empty">{documents.length ? "No files match this search." : "Loading local document index…"}</div>
            )}
          </div>
          {listError && <p className="inline-error"><AlertCircle size={14} />{listError}</p>}
          <label className={`upload-card ${uploading ? "busy" : ""}`}>
            <input
              ref={uploadInput}
              type="file"
              accept=".pdf,.png,.jpg,.jpeg,.svg,.dwg,.dxf,.ifc"
              onChange={(event) => void onUpload(event.target.files?.[0])}
            />
            {uploading ? <LoaderCircle className="spin" size={17} /> : <Upload size={17} />}
            <span><strong>{uploading ? "Adding to workspace…" : "Import a source file"}</strong><small>PDF, image, DXF, DWG, or IFC · 25 MiB max</small></span>
            <Plus size={16} className="upload-plus" />
          </label>
          <div className="library-footer">
            <span className="footer-status"><span className="live-dot" /> SOURCE INDEX</span>
            <span>VERIFIED SOURCE WORKSPACE</span>
          </div>
        </aside>

        <section className="workspace-main" aria-label="Drawing and model workspace">
          <div className="review-context">
            <div>
              <p className="review-kicker"><span className="live-dot" /> PLAN REVIEW BOARD <span>/</span> SOURCE TRUTH</p>
              <h2>{selected ? documentName(selected.path) : "Construction intelligence workspace"}</h2>
              <p className="review-subtitle">Evidence-linked review of drawings, quantities, and spatial relationships.</p>
            </div>
            <div className="review-context-actions">
              <span className="review-status"><ShieldCheck size={13} /> SOURCE-LINKED</span>
              <span className="review-level">LEVEL <strong>ALL</strong></span>
            </div>
          </div>
          <div className="workspace-toolbar">
            <div className="source-heading">
              <span className="source-type">{selected ? fileLabel(selected.format) : <FileImage size={14} />}</span>
              <div className="source-title">
                <strong title={selected?.path}>{selected ? documentName(selected.path) : "Select a source"}</strong>
                <small>{selected?.preview_relationship || "Evidence-linked drawing and model workspace"}</small>
              </div>
            </div>
            <div className="toolbar-right">
              {(selected?.format === "pdf" || selected?.preview_format === "pdf") && (
                <div className="page-nav" aria-label="PDF page navigation">
                  <button className="icon-button subtle" onClick={() => void loadPage(page - 1)} disabled={page <= 1} title="Previous page"><ChevronLeft size={16} /></button>
                  <span>{page} <i>/</i> {preview?.pageCount || selected.page_count || 1}</span>
                  <button className="icon-button subtle" onClick={() => void loadPage(page + 1)} disabled={page >= (preview?.pageCount || selected.page_count || 1)} title="Next page"><ChevronRight size={16} /></button>
                </div>
              )}
              <span className="toolbar-divider" />
              <div className="view-switch" aria-label="Workspace layout">
                <button className={viewMode === "split" ? "selected" : ""} onClick={() => setViewMode("split")} title="Side-by-side">
                  <Maximize2 size={14} />
                </button>
                <button className={viewMode === "drawing" ? "selected" : ""} onClick={() => setViewMode("drawing")} title="Drawing only">2D</button>
                <button className={viewMode === "model" ? "selected" : ""} onClick={() => setViewMode("model")} title="Model only">3D</button>
              </div>
            </div>
          </div>

          <div className="review-strip" aria-label="Review controls">
            <div className="layer-switch" role="group" aria-label="Evidence layers">
              <span className="layer-switch-label"><DraftingCompass size={13} /> REVIEW LAYERS</span>
              <button className={`layer-chip ${viewMode !== "model" ? "active" : ""}`} type="button" onClick={() => setViewMode("drawing")}><span className="layer-dot overview" />Detected overview</button>
              <button className={`layer-chip ${viewMode !== "model" ? "active" : ""}`} type="button" onClick={() => setViewMode("drawing")}><span className="layer-dot evidence" />Answer evidence</button>
              <button className={`layer-chip ${viewMode === "model" ? "active" : ""}`} type="button" onClick={() => setViewMode("model")}><span className="layer-dot model" />Spatial model</button>
            </div>
            <span className="review-hint">Click any highlighted region to inspect its source</span>
          </div>

          <div className="metric-strip" aria-label="Source quantities">
            <div className="metric-card"><span className="metric-label">SOURCE PAGES</span><strong>{preview?.pageCount || selected?.page_count || 1}</strong><small>indexed</small></div>
            <div className="metric-card"><span className="metric-label">MODEL ELEMENTS</span><strong>{scene?.elements.length || 0}</strong><small>{scene?.status === "partial" ? "illustrative" : "source-backed"}</small></div>
            <div className="metric-card"><span className="metric-label">OPENINGS</span><strong>{scene ? scene.elements.filter((element) => /door|window|opening/i.test(element.entity_type)).length : 0}</strong><small>doors + windows</small></div>
            <div className="metric-card metric-card-accent"><span className="metric-label">EVIDENCE LINKS</span><strong>{answer?.evidence.length || evidenceLayers.length}</strong><small>ready to verify</small></div>
          </div>

          <div className={`view-grid mode-${viewMode}`}>
            <section className={`viewport-panel drawing-panel ${viewMode === "model" ? "mode-hidden" : ""}`}>
              <div className="viewport-heading">
                <div><FileText size={14} /><span>2D SOURCE TRUTH</span></div>
                <span className="viewport-coordinate">{preview?.coordinateSystem?.replaceAll("_", " ") || "SOURCE VIEW"}</span>
              </div>
              <div className="drawing-stage">
                {preview ? (
                  <>
                    <div className="drawing-canvas-wrap" style={{
                      aspectRatio: `${preview.width || 1} / ${preview.height || 1}`,
                      transform: `scale(${zoom})`,
                      transformOrigin: zoomOrigin,
                    }}>
                      <img src={preview.url} alt={`Source drawing page ${page}`} />
                      {preview.width > 0 && preview.height > 0 && (
                        <svg
                          className="evidence-svg"
                          viewBox={preview.viewBox
                            ? preview.viewBox.join(" ")
                            : `0 0 ${preview.width} ${preview.height}`}
                          preserveAspectRatio="none"
                          aria-label="Evidence regions"
                        >
                          {rasterOverview.map(({ element, box }) => (
                            <g
                              key={`overview-${element.id}`}
                              className="scene-overview-shape"
                            >
                              <rect
                                x={box[0]}
                                y={box[1]}
                                width={Math.max(1, box[2] - box[0])}
                                height={Math.max(1, box[3] - box[1])}
                              />
                              <title>{`${element.name} - detected overview region`}</title>
                            </g>
                          ))}
                          {evidenceLayers.map((overlay) => {
                            const box = boxForOverlay(overlay);
                            const polygons = polygonsForOverlay(overlay);
                            return (
                              <g
                                key={overlay.overlay_id}
                                ref={(node) => { evidenceGroupRefs.current[overlay.overlay_id] = node; }}
                                className={`evidence-shape ${selectedEvidenceId === overlay.entity_id || selectedEvidenceId === overlay.overlay_id || overlay.evidence_ids.includes(selectedEvidenceId || "") ? "highlight" : ""}`}
                                onClick={() => selectEvidence(overlay.entity_id || overlay.overlay_id)}
                              >
                                {box && box.length >= 4 && (
                                  <rect x={box[0]} y={box[1]} width={box[2] - box[0]} height={box[3] - box[1]} />
                                )}
                                {polygons.map((points, index) => (
                                  <polygon key={index} points={points.map((point) => point.slice(0, 2).join(",")).join(" ")} />
                                ))}
                                <title>{overlay.label}</title>
                              </g>
                            );
                          })}
                        </svg>
                      )}
                    </div>
                    <div className="drawing-controls">
                      <button className="icon-button" onClick={() => setZoom((value) => Math.max(0.55, value - 0.15))} title="Zoom out"><ArrowDownRight size={14} /></button>
                      <span>{Math.round(zoom * 100)}%</span>
                      <button className="icon-button" onClick={() => setZoom((value) => Math.min(2.5, value + 0.15))} title="Zoom in"><ArrowUpRight size={14} /></button>
                      <button className="icon-button" onClick={() => { setZoom(1); setZoomOrigin("center"); }} title="Fit drawing"><Crosshair size={14} /></button>
                    </div>
                    {(rasterOverview.length > 0 || evidenceLayers.length > 0) && (
                      <div className="drawing-legend" aria-label="Drawing overlay legend">
                        {rasterOverview.length > 0 && <span><i className="legend-swatch overview" />Detected overview</span>}
                        {evidenceLayers.length > 0 && <span><i className="legend-swatch evidence" />Answer evidence</span>}
                      </div>
                    )}
                  </>
                ) : (
                  <div className="empty-viewport">
                    <div className="empty-glyph"><FileImage size={24} /></div>
                    <strong>{selected ? "2D preview unavailable" : "No source selected"}</strong>
                    <p>{previewNote}</p>
                    {selected && <span className="source-path">{selected.path}</span>}
                  </div>
                )}
              </div>
            </section>

            <section className={`viewport-panel model-panel ${viewMode === "drawing" ? "mode-hidden" : ""}`}>
              <div className="viewport-heading">
                <div><Box size={14} /><span>3D INTERPRETATION</span></div>
                {scene?.status !== "unavailable" && scene?.elements.length ? (
                  <span className="viewport-coordinate">{scene.elements.length} ELEMENTS · {scene.unit.toUpperCase()}</span>
                ) : (
                  <span className="viewport-coordinate">EVIDENCE ONLY</span>
                )}
              </div>
              <div className="model-stage">
                {scene?.elements.length ? (
                  <Suspense fallback={<div className="empty-viewport"><LoaderCircle className="spin loading-icon" size={27} /><strong>Loading 3D renderer</strong></div>}>
                    <SceneViewport scene={scene} selectedId={selectedEvidenceId} onSelect={selectElement} />
                  </Suspense>
                ) : sceneLoading ? (
                  <div className="empty-viewport">
                    <LoaderCircle className="spin loading-icon" size={27} />
                    <strong>Loading source model</strong>
                    <p>Preparing the geometry for inspection.</p>
                  </div>
                ) : (
                  <div className="empty-viewport">
                    <div className="empty-glyph"><Box size={25} /></div>
                    <strong>{sceneError ? "Spatial model unavailable" : selected ? "Build a spatial view" : "Select a model or drawing"}</strong>
                    <p>{sceneError || (selected?.format === "ifc"
                      ? "No source-backed 3D elements are available for this model."
                      : selected && sceneCapable(selected.format)
                        ? "Run local floor-plan segmentation to create a display-only 2.5D view."
                        : "Choose an IFC model to explore its native product geometry.")}</p>
                    {selected && sceneCapable(selected.format) && !sceneError && (
                      <button className="primary-button compact" onClick={() => void generateScene()}>
                        <Sparkles size={14} /> Reconstruct plan view
                      </button>
                    )}
                  </div>
                )}
                {scene?.status === "partial" && scene.warnings[0] && (
                  <div className="scene-warning"><AlertCircle size={13} />{scene.warnings[0]}</div>
                )}
                {scene?.has_more && (
                  <button
                    className="load-more"
                    disabled={sceneLoading}
                    onClick={async () => {
                      if (!selected) return;
                      const token = selectionToken.current;
                      setSceneLoading(true);
                      const nextOffset = sceneOffset + scene.limit;
                      try {
                        const pageResult = await api.scene(
                          selected.document_id,
                          scene.limit || 100,
                          nextOffset,
                        );
                        if (token !== selectionToken.current) return;
                        setScene((current) => current
                          ? { ...current, elements: [...current.elements, ...pageResult.elements], has_more: pageResult.has_more, offset: pageResult.offset }
                          : pageResult);
                        setSceneOffset(nextOffset);
                      } catch (error) {
                        if (token === selectionToken.current) {
                          setSceneError(error instanceof Error ? error.message : "The next geometry page failed.");
                        }
                      } finally {
                        if (token === selectionToken.current) setSceneLoading(false);
                      }
                    }}
                  >
                    {sceneLoading ? <LoaderCircle className="spin" size={13} /> : <ChevronDown size={13} />}
                    Load next geometry page
                  </button>
                )}
              </div>
              {selectedElement && (
                <div className="element-inspector">
                  <div className="inspector-icon" style={{ background: typeof selectedElement.provenance.display_color === "string" ? selectedElement.provenance.display_color : undefined }}>
                    <Box size={16} />
                  </div>
                  <div className="inspector-copy">
                    <strong>{selectedElement.name}</strong>
                    <span>{selectedElement.entity_type}{selectedElement.global_id ? ` · ${selectedElement.global_id}` : ""}</span>
                  </div>
                  <span className={`provenance-tag provenance-${String(selectedElement.provenance.status || "unknown")}`}>
                    {String(selectedElement.provenance.status || "unknown")}
                  </span>
                  <button className="icon-button" onClick={() => selectElement(null)} title="Clear selection"><X size={14} /></button>
                </div>
              )}
            </section>
          </div>
          <div className="workspace-statusbar">
            <span><MousePointer2 size={12} /> SELECT A REGION OR MODEL ELEMENT</span>
            <span>{selected?.path || "NO ACTIVE SOURCE"}</span>
            <span>{scene?.coordinate_system?.replaceAll("_", " ") || "LOCAL COORDINATES"}</span>
          </div>
        </section>

        <aside className="assistant-panel">
          <div className="assistant-heading">
            <div>
              <p className="eyebrow">VERIFICATION INSPECTOR</p>
              <h2>Ask the plan</h2>
            </div>
            <span className="assistant-mark"><MessageSquareText size={16} /></span>
          </div>
          <p className="assistant-intro">Turn a construction question into a checked quantity, location, and evidence trail.</p>

          <div className="active-source-card">
            <span className="active-source-icon"><FileText size={15} /></span>
            <span><small>ACTIVE SOURCE</small><strong>{selected ? documentName(selected.path) : "No source selected"}</strong></span>
            {selected && <Check size={14} className="source-check" />}
          </div>

          <div className="question-intents" aria-label="Question categories">
            <div className="question-intents-heading"><span>ASK BY INTENT</span><small>Choose a starting point</small></div>
            <div className="question-intent-list">
              {questionIntents.map(([label, prompt]) => (
                <button type="button" key={label} className="question-intent" onClick={() => setQuestion(prompt)} disabled={asking || !selected}>
                  <strong>{label}</strong><span>{prompt}</span>
                </button>
              ))}
            </div>
          </div>

          <form className="question-form"           onSubmit={(event) => void askQuestion(event)}>
            <label htmlFor="question">YOUR QUESTION</label>
            <textarea
              id="question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="e.g. How many doors are tagged on this plan?"
              maxLength={1000}
              disabled={!selected || asking}
            />
            <div className="composer-bottom">
              <span>{question.length}/1000</span>
              <button className="ask-button" type="submit" disabled={!selected || !question.trim() || asking}>
                {asking ? <LoaderCircle className="spin" size={15} /> : <Send size={14} />}
                {asking ? "Analyzing…" : "Run analysis"}
              </button>
            </div>
          </form>

          {demoPrompts.length > 0 && (
            <div className="demo-prompts">
              <div className="demo-prompts-title"><Sparkles size={12} /> VERIFIED STARTERS</div>
              <div className="demo-prompts-list">
                {demoPrompts.map(([label, prompt]) => (
                  <button
                    type="button"
                    className="demo-prompt"
                    key={prompt}
                    onClick={() => setQuestion(prompt)}
                    disabled={asking}
                  >
                    <strong>{label}</strong>
                    <span>{prompt}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {askError && <div className="inline-error answer-error"><AlertCircle size={14} />{askError}</div>}
          {asking && (
            <div className="analysis-progress">
              <span className="progress-orbit"><Sparkles size={15} /></span>
              <div><strong>Checking the original source</strong><small>Preparing a verifiable answer…</small></div>
            </div>
          )}
          {answer ? (
            <AnswerPanel
              answer={answer}
              onEvidence={focusEvidence}
            />
          ) : !asking && (
            <div className="query-hint">
              <Sparkles size={14} />
              <p><strong>One question at a time.</strong> Results include uncertainty and source evidence. No evidence means no supported claim.</p>
            </div>
          )}

          <div className="assistant-footer">
            <span><span className="live-dot" /> RESULT STATUS</span>
            <span>{asking ? "RUNNING" : answer ? answer.status.toUpperCase() : "READY"}</span>
          </div>
        </aside>
      </main>
    </div>
  );
}

function AnswerPanel({
  answer,
  onEvidence,
}: {
  answer: Answer;
  onEvidence: (evidence: EvidenceRef) => void;
}) {
  const statusLabel: Record<Answer["status"], string> = {
    supported: "SUPPORTED",
    partial: "PARTIAL",
    uncertain: "UNCERTAIN",
    unable: "UNABLE TO ANSWER",
    error: "ERROR",
  };
  return (
    <section className="answer-panel" aria-live="polite">
      <div className={`answer-status status-${answer.status}`}>
        <span><span className="status-dot" />{statusLabel[answer.status]}</span>
        <small>{answer.evidence.length} EVIDENCE REFERENCES</small>
      </div>
      <p className="answer-text">{answer.answer}</p>
      {answer.question_spec.corrections.length > 0 && (
        <div className="answer-detail"><span>QUESTION NORMALIZATION</span><p>Interpreted with: {answer.question_spec.corrections.join(", ")}</p></div>
      )}
      {answer.value !== undefined && answer.value !== null && (
        <div className="answer-value">{String(answer.value)}{answer.unit ? <small>{answer.unit}</small> : null}</div>
      )}
      {answer.calculation.length > 0 && (
        <div className="answer-detail"><span>CALCULATION</span>{answer.calculation.map((step, index) => <p key={index}>{step}</p>)}</div>
      )}
      {answer.evidence.length > 0 ? (
        <div className="evidence-list">
          <div className="section-label"><span>DOCUMENT EVIDENCE</span><span>{answer.evidence.length}</span></div>
          {answer.evidence.map((evidence, index) => (
            <button className="evidence-card" key={`${evidence.document_id}-${evidence.entity_id || index}`} onClick={() => onEvidence(evidence)} title="Focus this evidence in the drawing or model" aria-label={`Focus evidence ${index + 1}`}>
              <span className="evidence-index">{String(index + 1).padStart(2, "0")}</span>
              <span className="evidence-copy">
                <strong>{evidence.entity_type || evidence.path.split("/").pop()}</strong>
                <small>{evidence.page ? `Page ${evidence.page} · ` : ""}{evidence.extraction_method}</small>
                {evidence.extracted_content && <em>{evidence.extracted_content}</em>}
              </span>
              <ArrowUpRight size={13} />
            </button>
          ))}
        </div>
      ) : (
        <div className="no-evidence"><AlertCircle size={14} />No evidence reference was returned for this answer.</div>
      )}
      {answer.overlays.length > 0 && (
        <div className="overlay-note"><Crosshair size={13} />{answer.overlays.length} evidence region{answer.overlays.length === 1 ? "" : "s"} available on the drawing.</div>
      )}
      {answer.assumptions.length > 0 && (
        <div className="answer-detail"><span>ASSUMPTIONS</span>{answer.assumptions.map((item, index) => <p key={index}>{item}</p>)}</div>
      )}
      {answer.warnings.length > 0 && (
        <div className="answer-warnings">{answer.warnings.map((warning, index) => <p key={index}><AlertCircle size={13} />{warning}</p>)}</div>
      )}
      <div className="validation-note"><ShieldCheck size={13} />{answer.validation}</div>
    </section>
  );
}

export default App;
