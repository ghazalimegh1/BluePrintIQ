export interface Capability {
  capability_type: string;
  available: boolean;
  details: Record<string, unknown>;
  limitations: string[];
}

export interface DocumentRecord {
  document_id: string;
  path: string;
  source: string;
  format: string;
  size_bytes: number;
  capabilities: Capability[];
  ingestion_status: string;
  page_count?: number | null;
  preview_document_id?: string;
  preview_format?: string;
  preview_relationship?: string;
}

export interface SceneElement {
  id: string;
  global_id?: string | null;
  entity_type: string;
  name: string;
  geometry_kind: "triangle_mesh" | "polygon";
  vertices: number[];
  indices: number[];
  coordinate_system: string;
  unit: string;
  properties: Record<string, Record<string, unknown>>;
  relationships: Array<{
    relationship_type: string;
    target_id: string;
    provenance_status: string;
    confidence?: number | null;
  }>;
  provenance: Record<string, unknown>;
}

export interface SceneResponse {
  document_id: string;
  source_path: string;
  source_format: string;
  status: "ready" | "partial" | "unavailable";
  coordinate_system: string;
  unit: string;
  source_origin?: number[] | null;
  total_elements: number;
  offset: number;
  limit: number;
  has_more: boolean;
  elements: SceneElement[];
  warnings: string[];
}

export interface EvidenceRef {
  document_id: string;
  path: string;
  page?: number | null;
  entity_id?: string | null;
  entity_type?: string | null;
  extracted_content?: string | null;
  bbox?: number[] | null;
  geometry?: Record<string, unknown> | unknown[] | null;
  coordinate_system?: string | null;
  extraction_method: string;
  source_tool_version: string;
}

export interface EvidenceOverlay {
  overlay_id: string;
  document_id: string;
  page_or_view_id?: string | null;
  overlay_type: string;
  geometry?: Record<string, unknown> | unknown[] | null;
  coordinate_system: string;
  label: string;
  entity_id?: string | null;
  class_name?: string | null;
  source_tool: string;
  model_name?: string | null;
  is_model_output: boolean;
  evidence_ids: string[];
}

export interface PlanStep {
  tool_name: string;
  status: "queued" | "running" | "succeeded" | "failed" | "skipped";
  summary: string;
  evidence_count: number;
}

export interface Answer {
  status: "supported" | "partial" | "uncertain" | "unable" | "error";
  answer: string;
  value?: unknown;
  unit?: string | null;
  calculation: string[];
  evidence: EvidenceRef[];
  overlays: EvidenceOverlay[];
  warnings: string[];
  assumptions: string[];
  question_spec: {
    original_question: string;
    corrections: string[];
    operation: string;
    entity_concepts: string[];
    recommended_tools: string[];
    scope?: string | null;
    output_unit?: string | null;
    ambiguities: string[];
  };
  trace: PlanStep[];
  validation: string;
}

export interface LlmStatus {
  api_key_configured: boolean;
  model: string | null;
  gemini_vl_configured: boolean;
  gemini_vl_model: string | null;
}
