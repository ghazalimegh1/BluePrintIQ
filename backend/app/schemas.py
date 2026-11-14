from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Capability(BaseModel):
    capability_type: str
    available: bool
    details: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    coordinate_system: str | None = None


class DocumentRecord(BaseModel):
    document_id: str
    path: str
    source: str
    format: str
    size_bytes: int
    license_file: str | None = None
    license_credit: str | None = None
    capabilities: list[Capability] = Field(default_factory=list)
    ingestion_status: Literal["ready", "limited", "unsupported", "uninspected"] = "ready"
    page_count: int | None = None
    companion_document_id: str | None = None


class QuestionSpec(BaseModel):
    original_question: str
    corrections: list[str] = Field(default_factory=list)
    operation: Literal["count", "measure", "find_text", "calculate", "describe"]
    # The benchmark uses these five top-level labels.  Keep this separate from
    # ``operation`` because property/schedule questions are text-labelled even
    # when they ask for a numeric value (for example, door widths by type).
    question_type: Literal["count", "area", "length", "volume", "text", "other"] = "other"
    intent: Literal[
        "count", "measure", "retrieve", "aggregate", "compare", "summarize", "describe"
    ] = "describe"
    entity_concepts: list[str] = Field(default_factory=list)
    recommended_tools: list[str] = Field(default_factory=list)
    scope: str | None = None
    output_unit: str | None = None
    ambiguities: list[str] = Field(default_factory=list)


class LLMProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["groq"] = "groq"
    model: str = Field(min_length=1, max_length=200)


class ToolSpec(BaseModel):
    name: str
    version: str
    description: str
    operations: list[str]
    input_formats: list[str]
    deterministic: bool
    limitations: list[str] = Field(default_factory=list)


class PlanStep(BaseModel):
    tool_name: str
    status: Literal["queued", "running", "succeeded", "failed", "skipped"]
    summary: str
    evidence_count: int = 0


class EvidenceRef(BaseModel):
    document_id: str
    path: str
    page: int | None = None
    entity_id: str | None = None
    entity_type: str | None = None
    extracted_content: str | None = None
    bbox: list[float] | None = None
    geometry: dict[str, Any] | list[Any] | None = None
    coordinate_system: str | None = None
    extraction_method: str
    source_tool_version: str


class EvidenceOverlay(BaseModel):
    overlay_id: str
    document_id: str
    page_or_view_id: str | None = None
    overlay_type: Literal[
        "instance_mask", "semantic_mask", "polygon", "polyline", "bounding_box",
        "point", "dimension", "text_region", "ifc_selection"
    ]
    geometry: dict[str, Any] | list[Any] | None = None
    coordinate_system: str
    label: str
    entity_id: str | None = None
    class_name: str | None = None
    source_tool: str
    model_name: str | None = None
    is_model_output: bool
    evidence_ids: list[str] = Field(default_factory=list)


class SceneRelationship(BaseModel):
    relationship_type: str
    target_id: str
    provenance_status: Literal["explicit", "measured", "detected", "inferred", "illustrative", "unknown"]
    confidence: float | None = Field(default=None, ge=0, le=1)


class SceneElement(BaseModel):
    id: str
    global_id: str | None = None
    entity_type: str
    name: str
    geometry_kind: Literal["triangle_mesh", "polygon"]
    vertices: list[float]
    indices: list[int]
    coordinate_system: str
    unit: str
    properties: dict[str, dict[str, Any]] = Field(default_factory=dict)
    relationships: list[SceneRelationship] = Field(default_factory=list)
    provenance: dict[str, Any]


class SceneResponse(BaseModel):
    document_id: str
    source_path: str
    source_format: str
    status: Literal["ready", "partial", "unavailable"]
    coordinate_system: str
    unit: str
    source_origin: list[float] | None = None
    total_elements: int = 0
    offset: int = 0
    limit: int = 0
    has_more: bool = False
    elements: list[SceneElement] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SceneSelectionRequest(BaseModel):
    element_ids: list[str] = Field(min_length=1, max_length=500)


class ToolResult(BaseModel):
    status: Literal["supported", "partial", "abstain", "error"]
    value: Any = None
    unit: str | None = None
    calculation: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    overlays: list[EvidenceOverlay] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    error: str | None = None


class FinalAnswer(BaseModel):
    status: Literal["supported", "partial", "uncertain", "unable", "error"]
    answer: str
    value: Any = None
    unit: str | None = None
    calculation: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    overlays: list[EvidenceOverlay] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    question_spec: QuestionSpec
    trace: list[PlanStep] = Field(default_factory=list)
    validation: str


class AskRequest(BaseModel):
    document_id: str = Field(min_length=8, max_length=64)
    question: str = Field(min_length=3, max_length=1000)
    page_number: int | None = Field(default=None, ge=1)
    llm: LLMProviderConfig | None = None
    gemini_vl_consent: bool = False
