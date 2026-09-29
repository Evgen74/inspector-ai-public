"""Pydantic v2 models of the contract schemas (packages/contracts/schemas/*.schema.json).

The JSON Schemas are the source of truth; these models mirror them field by field for typed
Python code. `tests/test_contracts_models.py` fails when a model and its schema drift apart
(field sets) or when an example validates against one but not the other.

Models of our own artifacts forbid unknown fields (schemas use ``additionalProperties: false``);
models of organizer rows allow them (organizer vocabularies may grow).
"""

from __future__ import annotations

from typing import Annotated, Any, ClassVar, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from inspector_common.contracts.enums import (
    AiVerdict,
    ApprovalStatus,
    ArtifactFormat,
    ArtifactKind,
    CommentSource,
    ComparisonAxis,
    ComparisonResult,
    CompletenessBasis,
    CompletenessStatus,
    CriticalityLevel,
    DataType,
    DecidedBy,
    DecisionClarifyBasis,
    DecisionConfirmBasis,
    DecisionRejectReason,
    DecisionType,
    DeviationDirection,
    DiscoveryMethod,
    DiscrepancyType,
    DocStage,
    EvidenceBindStatus,
    EvidenceRole,
    ExtractionMethod,
    ExtractionRunStatus,
    FindingStatus,
    GoldEffect,
    HedgeKind,
    InspectorStatus,
    LoadScenario,
    LocalFileStatus,
    LocationType,
    ManifestSplit,
    ManifestStage,
    MatrixScope,
    PageBasis,
    PageClass,
    ParameterMappingStatus,
    PlannedAction,
    ProcessStatus,
    ProtocolParamStatus,
    ProtocolStatus,
    ProtocolSummaryRow,
    QualityFlag,
    ReviewPriority,
    RevisionBasis,
    RevisionCloudSource,
    RiskLevel,
    Role,
    RoomSource,
    RunStatus,
    ScenarioBase,
    SheetMapBasis,
    StageUploadStatus,
    SuspicionInspectorStatus,
    TableCheckKind,
    TableRowKind,
    TableType,
    TagKind,
    TagRoomLink,
    TextOrigin,
    TextSource,
    ViolationLabel,
    ViolationType,
    ZoneSource,
)

# ── Shared field types (common.schema.json $defs) ─────────────────────────────────────────────

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ManifestFileId = Annotated[str, StringConstraints(pattern=r"^(F[0-9]{4}|U[0-9a-f]{8}-[0-9]{4})$")]
FileId = Annotated[str, StringConstraints(min_length=1, max_length=512)]
CitableFileId = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[^!]+$")]
ObjectId = Annotated[str, StringConstraints(min_length=1, max_length=64)]
CanonicalParameterCode = Annotated[
    str, StringConstraints(pattern=r"^(PZ|SPZU|AR|KR|IOS[1-5]|POS|POD|OOS|PPM|ODI|ZU|SM)-[0-9]{3}$")
]
_FREE = r"FREE-(HEATING|VENTILATION|WATER|SEWER|ELECTRICAL|LIGHTING|FIRE|EVACUATION|ACCESSIBILITY|ARCHITECTURE|STRUCTURE|SITE|ROOF|FACADE|LIFT|ENERGY|OTHER)-[0-9]{3}"
SubmissionParameterCode = Annotated[
    str,
    StringConstraints(pattern=rf"^((PZ|SPZU|AR|KR|IOS[1-5]|POS|POD|OOS|PPM|ODI|ZU|SM)-[0-9]{{3}}|{_FREE})$"),
]
FreeParameterCode = Annotated[str, StringConstraints(pattern=rf"^{_FREE}$")]
ParamId = Annotated[int, Field(ge=1, le=132)]
PageNumber = Annotated[int, Field(ge=1)]
SheetNumber = str | int | None
Norm01 = Annotated[float, Field(ge=0.0, le=1.0)]
BBoxNorm = Annotated[list[Norm01], Field(min_length=4, max_length=4)]
PointNorm = Annotated[list[Norm01], Field(min_length=2, max_length=2)]
PolygonNorm = Annotated[list[PointNorm], Field(min_length=3)]
Rotation = Literal[0, 90, 180, 270]
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
Location = Annotated[str, StringConstraints(min_length=1, max_length=200)]
StageValue = str | int | float | bool | None
ErrorCodeStr = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]*$")]
CriticalityString = Literal[
    "Критическое (приостановка работ)",
    "Существенное (предписание)",
    "Существенное (предписание) — требует утверждения",
]
GeometrySpace = Literal["PDF_VISIBLE_ROTATED_TL_V1"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, use_enum_values=False)

    def dump(self) -> dict[str, Any]:
        """JSON-ready dict without unset optional fields."""
        return self.model_dump(mode="json", exclude_unset=True)


class _Open(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class Geometry(_Strict):
    boxes: list[BBoxNorm] | None = None
    polygons: list[PolygonNorm] | None = None


class Versions(_Strict):
    matrix_version: str | None = None
    dataset_version: str | None = None
    model_version: str | None = None
    pipeline_version: Annotated[str, StringConstraints(min_length=1)]
    code_version: str | None = None
    contract_version: str | None = None
    engine_versions: dict[str, str] | None = None


# ── EvidenceRef (evidence_ref.schema.json) ────────────────────────────────────────────────────


class EvidenceRef(_Strict):
    stage: DocStage
    file_id: CitableFileId
    pdf_page_number: PageNumber
    document_sheet_number: SheetNumber = None
    file_sha256: Sha256 | None = None
    page_basis: PageBasis | None = None
    role: EvidenceRole | None = None
    is_anchor: bool | None = None
    geometry: Geometry | None = None
    geometry_space: GeometrySpace | None = None
    localization: str | None = None
    document_code: str | None = None
    revision: str | None = None
    extracted_value_id: str | None = None
    note: str | None = None


# ── Finding (finding.schema.json) ─────────────────────────────────────────────────────────────


class Finding(_Strict):
    finding_id: Annotated[str, StringConstraints(min_length=1, max_length=96)]
    finding_group_id: str | None = None
    object_id: ObjectId
    run_id: str | None = None
    matrix_scope: MatrixScope
    parameter_code: SubmissionParameterCode
    parameter_id: ParamId | None = None
    parameter_mapping_status: ParameterMappingStatus | None = None
    alt_parameter_codes: list[CanonicalParameterCode] | None = None
    hedge_of_finding_id: str | None = None
    location: Location
    location_type: LocationType
    pd_value: StageValue = None
    rd_value: StageValue = None
    id_value: StageValue = None
    axis: ComparisonAxis | None = None
    comparison_result: ComparisonResult | None = None
    discrepancy_type: DiscrepancyType | None = None
    violation_type: ViolationType | None = None
    completeness_status: CompletenessStatus | None = None
    completeness_basis: CompletenessBasis | None = None
    finding_status: FindingStatus | None = None
    inspector_status: InspectorStatus | None = None
    violation_label: ViolationLabel
    protocol_status: ProtocolParamStatus
    criticality: CriticalityString | None
    criticality_level: CriticalityLevel | None = None
    review_priority: ReviewPriority | None = None
    risk_level: RiskLevel | None = None
    document_status: str | None = None
    confidence: Confidence | None = None
    evidence: list[EvidenceRef]
    hedge_kind: HedgeKind | None = None
    element_noun: str | None = None
    discovery_method: DiscoveryMethod | None = None
    evidence_bind_status: EvidenceBindStatus | None = None
    recommendation: Recommendation | None = None
    card_no: CardNo | None = None
    rule_code: str | None = None
    rule_version: str | None = None
    sub_id: str | None = None
    delta: dict[str, Any] | None = None
    rationale: str | None = None
    decision_trace: dict[str, Any] | None = None
    ext: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _consistency(self) -> Finding:
        from inspector_common.contracts.status import is_consistent

        is_free = self.parameter_code.startswith("FREE-")
        if (self.matrix_scope == MatrixScope.FREE_SEARCH) != is_free:
            raise ValueError("FREE-* codes go with matrix_scope FREE_SEARCH, catalog codes with MATRIX")
        if is_free and self.parameter_id is not None:
            raise ValueError("FREE-* findings have parameter_id null")
        if not is_consistent(self.violation_label, self.protocol_status):
            raise ValueError(
                f"protocol_status {self.protocol_status} contradicts violation_label {self.violation_label}"
            )
        return self


# ── PageTokens (page_tokens.schema.json) ──────────────────────────────────────────────────────


class PageInfo(_Strict):
    width_pt: Annotated[float, Field(gt=0)]
    height_pt: Annotated[float, Field(gt=0)]
    rotate: Rotation
    content_rotation: Rotation | None = None
    mediabox: Annotated[list[float], Field(min_length=4, max_length=4)] | None = None
    cropbox: Annotated[list[float], Field(min_length=4, max_length=4)] | None = None
    native_dpi: Annotated[int, Field(ge=1)] | None = None
    render_dpi: Annotated[int, Field(ge=1)] | None = None


class Token(_Strict):
    id: Annotated[int, Field(ge=0)]
    text: str
    text_raw: str | None = None
    corrected_by: str | None = None
    bbox: BBoxNorm
    polygon: PolygonNorm | None = None
    conf: Confidence
    source: TextSource
    angle: Rotation | None = None
    line_id: Annotated[int, Field(ge=0)] | None = None
    block_id: Annotated[int, Field(ge=0)] | None = None
    layer: str | None = None
    font: str | None = None
    font_size_pt: Annotated[float, Field(gt=0)] | None = None
    quality_flag: QualityFlag | None = None


class Line(_Strict):
    id: Annotated[int, Field(ge=0)]
    text: str
    bbox: BBoxNorm
    polygon: PolygonNorm | None = None
    token_ids: list[Annotated[int, Field(ge=0)]]
    conf: Confidence | None = None
    source: TextSource | None = None
    angle: Rotation | None = None


class Zone(_Strict):
    kind: Annotated[str, StringConstraints(min_length=1)]  # ZoneKind is an open vocabulary
    bbox: BBoxNorm
    polygon: PolygonNorm | None = None
    quality_flag: QualityFlag | None = None
    conf: Confidence | None = None
    source: ZoneSource | None = None
    attrs: dict[str, Any] | None = None


class PageTokens(_Strict):
    schema_version: Literal[1] = 1
    file_id: FileId
    file_sha256: Sha256
    page_no: PageNumber
    page_basis: PageBasis
    geometry_space: GeometrySpace = "PDF_VISIBLE_ROTATED_TL_V1"
    page: PageInfo
    page_class: PageClass | None = None
    text_source: TextSource | None = None
    is_stamp_page: bool | None = None
    quality_flag: QualityFlag | None = None
    mean_conf: Confidence | None = None
    coverage: Confidence | None = None
    layers: list[str] | None = None
    pipeline_version: Annotated[str, StringConstraints(min_length=1)]
    engine_versions: dict[str, str] | None = None
    timings_ms: dict[str, Annotated[float, Field(ge=0)]] | None = None
    warnings: list[ErrorCodeStr] | None = None
    tokens: list[Token]
    lines: list[Line] | None = None
    zones: list[Zone] | None = None
    ext: dict[str, Any] | None = None


# ── ExtractedValue (extracted_value.schema.json) ──────────────────────────────────────────────


class ValueNorm(_Strict):
    type: DataType
    value: Any
    unit: str | None = None
    rank: float | None = None
    range: Annotated[list[float], Field(min_length=2, max_length=2)] | None = None
    qualifiers: dict[str, Any] | None = None


class Anchor(_Strict):
    text: str | None = None
    geometry: Geometry | None = None


class TableRef(_Strict):
    table_id: str | None = None
    table_type: str | None = None
    row: Annotated[int, Field(ge=0)] | None = None
    col: Annotated[int, Field(ge=0)] | None = None


class ExtractedValue(_Strict):
    value_id: Annotated[str, StringConstraints(min_length=1)]
    object_id: ObjectId | None = None
    file_id: FileId
    file_sha256: Sha256
    stage: DocStage
    page_no: PageNumber
    page_basis: PageBasis | None = None
    sheet_label: SheetNumber = None
    document_code: str | None = None
    revision: str | None = None
    param_id: ParamId | None = None
    param_code: CanonicalParameterCode | None = None
    fact_key: str | None = None
    location: Location | None = None
    location_type: LocationType | None = None
    value_raw: str
    value_norm: ValueNorm
    unit_raw: str | None = None
    method: ExtractionMethod
    text_source: TextSource | None = None
    source_engine: str | None = None
    confidence: Confidence
    quality_flag: QualityFlag
    is_ambiguous: bool | None = None
    candidate_rank: Annotated[int, Field(ge=1)] | None = None
    geometry: Geometry | None = None
    geometry_space: GeometrySpace | None = None
    anchor: Anchor | None = None
    context_text: str | None = None
    table_ref: TableRef | None = None
    locator: dict[str, Any] | None = None
    pipeline_version: Annotated[str, StringConstraints(min_length=1)]
    matrix_version: str | None = None
    ext: dict[str, Any] | None = None


# ── RunManifest (run_manifest.schema.json) ────────────────────────────────────────────────────


class RunInputs(_Strict):
    manifest_sha256: Sha256
    catalog_sha256: Sha256
    submission_schema_sha256: Sha256
    split_policy_sha256: Sha256 | None = None
    models_manifest_sha256: Sha256 | None = None


class HostInfo(_Strict):
    platform: str | None = None
    machine: str | None = None
    python: str | None = None
    cpu_count: Annotated[int, Field(ge=1)] | None = None
    onnxruntime_providers: list[str] | None = None


class ObjectArtifacts(_Strict):
    inventory: str | None = None
    submission: str | None = None
    submission_strict: str | None = None
    sidecar: str | None = None
    findings: str | None = None
    finding_groups: str | None = None
    values: str | None = None
    protocol_json: str | None = None
    protocol_docx: str | None = None
    protocol_pdf: str | None = None
    score: str | None = None


class RunObject(_Strict):
    object_id: ObjectId
    name: str | None = None
    split: ManifestSplit
    input_manifest_hash: Sha256
    files_total: Annotated[int, Field(ge=0)]
    files_present: Annotated[int, Field(ge=0)]
    missing_on_disk: list[FileId]
    scenario: LoadScenario | None = None
    checks_total: Annotated[int, Field(ge=0)] | None = None
    artifacts: ObjectArtifacts | None = None


class RunFile(_Strict):
    file_id: FileId
    object_id: ObjectId
    sha256: Sha256
    manifest_stage: ManifestStage
    relative_path: Annotated[str, StringConstraints(min_length=1)] | None = None
    section: Annotated[str, StringConstraints(min_length=1)] | None = None  # open ManifestSection vocabulary
    size_bytes: Annotated[int, Field(ge=0)] | None = None
    stage_resolved: DocStage | None = None
    local_status: LocalFileStatus
    sha256_verified: bool | None = None
    extension: str | None = None
    pdf_pages: Annotated[int, Field(ge=0)] | None = None
    page_basis: PageBasis | None = None
    status: ExtractionRunStatus | None = None
    pages_ocr: Annotated[int, Field(ge=0)] | None = None
    duration_ms: Annotated[int, Field(ge=0)] | None = None
    error_code: ErrorCodeStr | None = None
    warnings: list[ErrorCodeStr] | None = None


class RunManifest(_Strict):
    schema_version: Literal[1] = 1
    run_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]
    producer: Literal["inspector-batch"] = "inspector-batch"
    command: str | None = None
    started_at: str
    finished_at: str | None = None
    status: RunStatus
    config_hash: Sha256
    stage_config_hashes: dict[str, Sha256] | None = None
    freeze_tag: str | None = None
    versions: Versions
    inputs: RunInputs
    host: HostInfo | None = None
    objects: Annotated[list[RunObject], Field(min_length=1)]
    files: list[RunFile]
    timings_s: dict[str, Annotated[float, Field(ge=0)]] | None = None
    warnings: list[ErrorCodeStr] | None = None
    ext: dict[str, Any] | None = None


# ── Submission (submission.extended / submission.strict / submission.organizer) ───────────────


class SubmissionEvidence(_Strict):
    stage: DocStage
    file_id: ManifestFileId
    pdf_page_number: PageNumber
    document_sheet_number: SheetNumber = None


class SubmissionCheck(_Strict):
    """A row of the full (extended) submission; `to_strict()` gives the organizer-fields-only row."""

    parameter_code: SubmissionParameterCode
    location: Location
    pd_value: StageValue = None
    rd_value: StageValue = None
    id_value: StageValue = None
    violation_label: ViolationLabel
    protocol_status: ProtocolParamStatus | None = None
    criticality: CriticalityString | None = None
    evidence: list[SubmissionEvidence]
    comparison_result: ComparisonResult | None = None
    location_type: LocationType | None = None
    document_status: str | None = None
    matrix_scope: MatrixScope | None = None
    parameter_mapping_status: ParameterMappingStatus | None = None
    finding_id: Annotated[str, StringConstraints(min_length=1)] | None = None
    confidence: Confidence | None = None

    STRICT_FIELDS: ClassVar[tuple[str, ...]] = (
        "parameter_code",
        "location",
        "pd_value",
        "rd_value",
        "id_value",
        "violation_label",
        "protocol_status",
        "criticality",
        "evidence",
    )

    def to_strict(self) -> dict[str, Any]:
        row = self.model_dump(mode="json", include=set(self.STRICT_FIELDS))
        row["evidence"] = [
            {"stage": e["stage"], "file_id": e["file_id"], "pdf_page_number": e["pdf_page_number"]}
            for e in row["evidence"]
        ]
        return {name: row.get(name) for name in self.STRICT_FIELDS}


class Submission(_Strict):
    object_id: ObjectId
    checks: list[SubmissionCheck]

    def to_strict(self) -> dict[str, Any]:
        return {"object_id": self.object_id, "checks": [c.to_strict() for c in self.checks]}


# ── Organizer rows (manifest, catalog, gold) — open models ────────────────────────────────────


class ManifestRow(_Open):
    schema_version: str
    file_id: ManifestFileId
    object_id: ObjectId
    corpus: str
    dataset_role: str
    split: ManifestSplit
    relative_path: Annotated[str, StringConstraints(min_length=1)]
    extension: Annotated[str, StringConstraints(pattern=r"^\.[a-z0-9]+$")]
    size_bytes: Annotated[int, Field(ge=0)]
    sha256: Sha256
    stage: ManifestStage
    section: str
    pdf_pages: Annotated[int, Field(ge=0)] | None
    annotation_status: str
    exclusion_reason: str | None
    duplicate_group: str | None
    distribution_status: str
    label_visibility: str


class CatalogRow(_Open):
    parameter_id: ParamId
    parameter_code: CanonicalParameterCode
    pd_section: Annotated[str, StringConstraints(min_length=1)]
    parameter_name: Annotated[str, StringConstraints(min_length=1)]
    unit: str | None
    source_pd: str | None
    source_rd: str | None
    source_id: str | None
    trigger: str | None
    criticality: Literal["Критическое (приостановка работ)", "Существенное (предписание)"]
    matrix_row: Annotated[int, Field(ge=1)]
    mapping_status: ParameterMappingStatus


class GoldEvidence(_Open):
    stage: DocStage
    file_id: ManifestFileId
    pdf_page_number: PageNumber
    document_sheet_number: SheetNumber = None
    rendered_image: str | None = None
    localization: str | None = None


class GoldCheck(_Open):
    check_id: Annotated[str, StringConstraints(min_length=1)]
    finding_group_id: Annotated[str, StringConstraints(min_length=1)]
    object_id: ObjectId
    split: ManifestSplit
    visibility: str | None = None
    matrix_scope: MatrixScope
    parameter_id: ParamId | None = None
    parameter_code: SubmissionParameterCode
    location_type: LocationType
    location: Location
    pd_value: StageValue = None
    rd_value: StageValue = None
    id_value: StageValue = None
    comparison_result: ComparisonResult | None = None
    violation_label: ViolationLabel
    protocol_status: ProtocolParamStatus
    criticality: CriticalityString | None
    document_status: str | None = None
    inspector_status: str | None = None
    gold_status: str | None = None
    score_eligible: bool | None = None
    evidence: list[GoldEvidence]


class GoldGroup(_Open):
    finding_group_id: Annotated[str, StringConstraints(min_length=1)]
    object_id: ObjectId
    split: ManifestSplit
    matrix_scope: MatrixScope
    parameter_id: ParamId | None = None
    parameter_code: SubmissionParameterCode
    parameter_mapping_status: ParameterMappingStatus
    title: str | None = None
    difference_type: ComparisonResult
    locations: Annotated[list[Location], Field(min_length=1)]
    criticality: CriticalityString | None
    source_label: str | None = None
    gold_status: str | None = None
    evidence: list[GoldEvidence]


# ── Finding groups (finding_group.schema.json) ────────────────────────────────────────────────

CardNo = Annotated[str, StringConstraints(pattern=r"^Б\.[1-9][0-9]*$")]


class Recommendation(_Strict):
    text: Annotated[str, StringConstraints(min_length=1)]
    template_id: str | None = None
    text_origin: TextOrigin | None = None
    work_type: str | None = None
    normative_refs: list[str] | None = None


class FindingGroup(_Strict):
    """One discrepancy before the atomic split; owns one anchor page per stage (97 §2.5, 93 §2.8)."""

    finding_group_id: Annotated[str, StringConstraints(min_length=1, max_length=96)]
    object_id: ObjectId
    run_id: str | None = None
    matrix_scope: MatrixScope
    parameter_code: SubmissionParameterCode
    parameter_id: ParamId | None = None
    parameter_mapping_status: ParameterMappingStatus | None = None
    alt_parameter_codes: list[CanonicalParameterCode] | None = None
    hedge_kind: HedgeKind | None = None
    hedge_of_group_id: str | None = None
    title: str | None = None
    element_noun: str | None = None
    axis: ComparisonAxis | None = None
    comparison_result: ComparisonResult
    discrepancy_type: DiscrepancyType | None = None
    location_type: LocationType
    locations: Annotated[list[Location], Field(min_length=1)]
    pd_value: StageValue = None
    rd_value: StageValue = None
    id_value: StageValue = None
    violation_label: ViolationLabel
    protocol_status: ProtocolParamStatus
    criticality: CriticalityString
    criticality_level: CriticalityLevel | None = None
    finding_status: FindingStatus | None = None
    risk_level: RiskLevel | None = None
    confidence: Confidence | None = None
    anchor_evidence: Annotated[list[EvidenceRef], Field(min_length=1, max_length=3)]
    evidence: list[EvidenceRef] | None = None
    location_pages: dict[str, list[EvidenceRef]] | None = None
    finding_ids: Annotated[list[Annotated[str, StringConstraints(min_length=1)]], Field(min_length=1)]
    discovery_method: DiscoveryMethod | None = None
    evidence_bind_status: EvidenceBindStatus | None = None
    rule_code: str | None = None
    rule_version: str | None = None
    rationale: str | None = None
    recommendation: Recommendation | None = None
    card_no: CardNo | None = None
    decision_trace: dict[str, Any] | None = None
    ext: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _consistency(self) -> FindingGroup:
        from inspector_common.contracts.status import is_consistent

        is_free = self.parameter_code.startswith("FREE-")
        if (self.matrix_scope == MatrixScope.FREE_SEARCH) != is_free:
            raise ValueError("FREE-* codes go with matrix_scope FREE_SEARCH, catalog codes with MATRIX")
        if is_free and self.parameter_id is not None:
            raise ValueError("FREE-* groups have parameter_id null")
        if not is_consistent(self.violation_label, self.protocol_status):
            raise ValueError(
                f"protocol_status {self.protocol_status} contradicts violation_label {self.violation_label}"
            )
        if len(set(self.locations)) != len(self.locations):
            raise ValueError("locations must be unique")
        if len(set(self.finding_ids)) != len(self.finding_ids):
            raise ValueError("finding_ids must be unique")
        return self


# ── Decision (decision.schema.json) ───────────────────────────────────────────────────────────


class Decision(_Strict):
    """An inspector verdict (ТЗ §9.3, 05 §3.6). Lives in the web product only; never exported."""

    decision_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    finding_id: Annotated[str, StringConstraints(min_length=1, max_length=96)]
    finding_group_id: str | None = None
    object_id: ObjectId
    run_id: str | None = None
    process_id: str | None = None
    protocol_version: Annotated[int, Field(ge=1)] | None = None
    decision: DecisionType
    effective_status: InspectorStatus | None = None
    reason_code: DecisionRejectReason | None = None
    basis_code: DecisionConfirmBasis | None = None
    clarify_code: DecisionClarifyBasis | None = None
    comment: Annotated[str, StringConstraints(min_length=1, max_length=4000)]
    comment_source: CommentSource | None = None
    approved_change_ref: str | None = None
    approved_change_file_id: CitableFileId | None = None
    approved_change_page: PageNumber | None = None
    corrected_value: StageValue = None
    correct_file_id: CitableFileId | None = None
    correct_locus: str | None = None
    duplicate_of: str | None = None
    na_basis: str | None = None
    justification: str | None = None
    authoritative_file_id: CitableFileId | None = None
    authoritative_basis_code: RevisionBasis | None = None
    authoritative_basis_text: str | None = None
    planned_action: PlannedAction | None = None
    ai_verdict: AiVerdict | None = None
    ai_confidence: Confidence | None = None
    ai_comment: str | None = None
    system_comment: str | None = None
    gold_effect: GoldEffect | None = None
    evidence_fingerprint: Sha256 | None = None
    override_of_decision_id: str | None = None
    decided_by: Annotated[str, StringConstraints(min_length=1)]
    decided_role: Role | None = None
    decided_at: str
    ext: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _rules(self) -> Decision:
        if self.decision == DecisionType.NEGATIVE_VERIFIED:
            if self.reason_code is None:
                raise ValueError("NEGATIVE_VERIFIED needs reason_code")
            if self.basis_code is not None or self.clarify_code is not None:
                raise ValueError("NEGATIVE_VERIFIED carries reason_code only")
        elif self.decision == DecisionType.CONFIRMED_VIOLATION:
            if self.reason_code is not None or self.clarify_code is not None:
                raise ValueError("CONFIRMED_VIOLATION carries basis_code only")
        elif self.decision == DecisionType.CLARIFICATION_REQUIRED:
            if self.clarify_code is None:
                raise ValueError("CLARIFICATION_REQUIRED needs clarify_code")
            if self.reason_code is not None or self.basis_code is not None:
                raise ValueError("CLARIFICATION_REQUIRED carries clarify_code only")
        # A rejection needs only its reason code; the comment and per-reason fields are optional
        # (product owner decision 29.09, decision.schema.json).
        return self


# ── Layout artifacts (layout_artifacts.schema.json) ───────────────────────────────────────────


class LayoutProvenance(_Strict):
    text_source: TextSource | None = None
    confidence: Confidence | None = None
    layer: str | None = None


class ChangeRow(_Strict):
    change_no: str | None = None
    count: str | None = None
    sheet: str | None = None
    doc_no: str | None = None
    date: str | None = None
    note: str | None = None


class TitleBlock(_Strict):
    pdf_page_number: PageNumber
    bbox: BBoxNorm | None = None
    sheet_number: SheetNumber = None
    sheets_total: Annotated[int, Field(ge=1)] | None = None
    document_code_raw: str | None = None
    document_code: str | None = None
    stage_raw: str | None = None
    stage: DocStage | None = None
    sheet_title: str | None = None
    object_name: str | None = None
    organization: str | None = None
    revision: str | None = None
    change_rows: list[ChangeRow] | None = None
    is_stamp_page: bool | None = None
    provenance: LayoutProvenance | None = None
    fields_confidence: dict[str, Confidence] | None = None


class SheetPageEntry(_Strict):
    pdf_page_number: PageNumber
    sheet_number: SheetNumber = None
    document_code: str | None = None
    basis: SheetMapBasis
    confidence: Confidence | None = None
    duplicate_of_page: PageNumber | None = None
    sheet_title: str | None = None


class RoomEntry(_Strict):
    room_token: Annotated[str, StringConstraints(min_length=1, max_length=32)]
    pdf_page_number: PageNumber
    bbox: BBoxNorm | None = None
    zone: PolygonNorm | None = None
    source: RoomSource
    name: str | None = None
    area_m2: Annotated[float, Field(ge=0)] | None = None
    floor: str | None = None
    sheet_number: SheetNumber = None
    provenance: LayoutProvenance | None = None


class TagInstance(_Strict):
    tag: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    tag_norm: str | None = None
    tag_kind: TagKind
    system_code: str | None = None
    pdf_page_number: PageNumber
    bbox: BBoxNorm | None = None
    room_token: str | None = None
    room_link: TagRoomLink | None = None
    provenance: LayoutProvenance | None = None


class CadLayer(_Strict):
    name: Annotated[str, StringConstraints(min_length=1)]
    xref: Annotated[int, Field(ge=0)] | None = None
    visible_default: bool | None = None
    pages: list[PageNumber] | None = None
    is_text_layer: bool | None = None
    is_revision_layer: bool | None = None
    revision_label: str | None = None
    discipline_hint: str | None = None


class RevisionCloud(_Strict):
    pdf_page_number: PageNumber
    bbox: BBoxNorm
    polygon: PolygonNorm | None = None
    source: RevisionCloudSource
    layer: str | None = None
    revision_label: str | None = None
    rooms_covered: list[Annotated[str, StringConstraints(min_length=1)]] | None = None
    confidence: Confidence | None = None


class QrLink(_Strict):
    pdf_page_number: PageNumber
    bbox: BBoxNorm | None = None
    payload: Annotated[str, StringConstraints(min_length=1)]
    doc_key: str | None = None
    doc_page: Annotated[int, Field(ge=1)] | None = None
    target_file_id: CitableFileId | None = None
    target_pdf_page_number: PageNumber | None = None


class LayoutArtifacts(_Strict):
    """runs/<run_id>/layout/<file_id>.json (AG-02B)."""

    schema_version: Literal[1] = 1
    file_id: CitableFileId
    object_id: ObjectId
    file_sha256: Sha256
    stage: DocStage | None = None
    pipeline_version: Annotated[str, StringConstraints(min_length=1)]
    generated_at: str
    pages_total: Annotated[int, Field(ge=0)]
    title_blocks: list[TitleBlock] | None = None
    sheet_page_map: list[SheetPageEntry] | None = None
    rooms: list[RoomEntry] | None = None
    tags: list[TagInstance] | None = None
    cad_layers: list[CadLayer] | None = None
    revision_clouds: list[RevisionCloud] | None = None
    qr_links: list[QrLink] | None = None
    warnings: list[ErrorCodeStr] | None = None
    timings_ms: dict[str, Annotated[float, Field(ge=0)]] | None = None
    ext: dict[str, Any] | None = None


# ── Table artifacts (table_artifacts.schema.json) ─────────────────────────────────────────────


class PageBox(_Strict):
    pdf_page_number: PageNumber
    bbox: BBoxNorm


class TableColumn(_Strict):
    key: Annotated[str, StringConstraints(min_length=1)]
    header_raw: str | None = None
    unit: str | None = None


class TableCell(_Strict):
    raw: str | None
    value: str | int | float | bool | None = None
    unit: str | None = None
    bbox: BBoxNorm | None = None
    pdf_page_number: PageNumber | None = None
    confidence: Confidence | None = None


class TableRow(_Strict):
    row_no: Annotated[int, Field(ge=1)]
    cells: dict[str, TableCell]
    pdf_page_number: PageNumber | None = None
    bbox: BBoxNorm | None = None
    kind: TableRowKind | None = None
    parent_row_no: Annotated[int, Field(ge=1)] | None = None
    section: str | None = None


class TableCheck(_Strict):
    kind: TableCheckKind
    passed: bool
    expected: float | str | None = None
    actual: float | str | None = None
    rows: list[Annotated[int, Field(ge=1)]] | None = None
    detail: str | None = None


def table_columns(table_type: TableType | str) -> tuple[str, ...]:
    """Canonical cell keys of a TableType (enums.yaml `columns`)."""
    from inspector_common.contracts.loader import load_enums

    return tuple(load_enums()["TableType"].value(str(table_type)).attrs["columns"])


class TypedTable(_Strict):
    table_id: Annotated[str, StringConstraints(min_length=1, max_length=96)]
    table_type: TableType
    title: str | None = None
    pages: Annotated[list[PageNumber], Field(min_length=1)]
    bboxes: list[PageBox] | None = None
    columns: Annotated[list[TableColumn], Field(min_length=1)]
    rows: list[TableRow]
    checks: list[TableCheck] | None = None
    sheet_number: SheetNumber = None
    document_code: str | None = None
    text_source: TextSource | None = None
    confidence: Confidence | None = None
    parser_version: str | None = None

    @model_validator(mode="after")
    def _columns_of_type(self) -> TypedTable:
        allowed = set(table_columns(self.table_type))
        keys = {c.key for c in self.columns} | {k for r in self.rows for k in r.cells}
        unknown = keys - allowed
        if unknown:
            raise ValueError(f"{self.table_type}: unknown column keys {sorted(unknown)}")
        return self


class TableArtifacts(_Strict):
    """runs/<run_id>/tables/<file_id>.json (AG-02C)."""

    schema_version: Literal[1] = 1
    file_id: CitableFileId
    object_id: ObjectId
    file_sha256: Sha256
    stage: DocStage | None = None
    pipeline_version: Annotated[str, StringConstraints(min_length=1)]
    generated_at: str
    tables: list[TypedTable]
    warnings: list[ErrorCodeStr] | None = None
    timings_ms: dict[str, Annotated[float, Field(ge=0)]] | None = None
    ext: dict[str, Any] | None = None


# ── Run artifacts index and tokens index ──────────────────────────────────────────────────────


def _relative_posix(path: str) -> str:
    if path.startswith("/") or ".." in path or "\\" in path:
        raise ValueError("path must be relative to the run directory, POSIX style, without '..'")
    return path


RelPath = Annotated[str, StringConstraints(min_length=1, max_length=512), AfterValidator(_relative_posix)]


class ArtifactProducer(_Strict):
    agent: Annotated[str, StringConstraints(pattern=r"^AG-[0-9]{2}[A-Z]?$")] | None = None
    command: Annotated[str, StringConstraints(min_length=1)] | None = None


class Artifact(_Strict):
    kind: ArtifactKind
    path: RelPath
    format: ArtifactFormat
    schema_name: str | None = None
    object_id: ObjectId | None = None
    file_id: FileId | None = None
    sha256: Sha256
    size_bytes: Annotated[int, Field(ge=0)]
    records: Annotated[int, Field(ge=0)] | None = None
    producer: ArtifactProducer | None = None
    modified_at: str | None = None


class PageTokensDir(_Strict):
    file_id: FileId
    object_id: ObjectId | None = None
    dir: Annotated[str, StringConstraints(min_length=1)]
    pages: Annotated[int, Field(ge=0)]
    size_bytes: Annotated[int, Field(ge=0)] | None = None


class RunArtifacts(_Strict):
    """runs/<run_id>/artifacts.json (AG-00): every file of the run with kind, sha256 and size."""

    schema_version: Literal[1] = 1
    layout_version: Literal["1"] = "1"
    run_id: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")]
    generated_at: str
    objects: list[ObjectId] | None = None
    commands: list[Annotated[str, StringConstraints(min_length=1)]] | None = None
    artifacts: list[Artifact]
    page_tokens: list[PageTokensDir] | None = None
    ext: dict[str, Any] | None = None


class TokensPageEntry(_Strict):
    pdf_page_number: PageNumber
    path: Annotated[str, StringConstraints(min_length=1)]
    page_class: PageClass | None = None
    text_sources: list[TextSource] | None = None
    quality_flag: QualityFlag | None = None
    rotation: Rotation | None = None
    tokens: Annotated[int, Field(ge=0)] | None = None
    has_layers: bool | None = None
    cache_hit: bool | None = None


class TokensFileEntry(_Strict):
    file_id: FileId
    object_id: ObjectId | None = None
    file_sha256: Sha256
    stage: DocStage | None = None
    pages_total: Annotated[int, Field(ge=0)]
    pages: list[TokensPageEntry]


class TokensIndex(_Strict):
    """runs/<run_id>/tokens/index.json (AG-02A)."""

    schema_version: Literal[1] = 1
    run_id: Annotated[str, StringConstraints(min_length=1)]
    pipeline_version: Annotated[str, StringConstraints(min_length=1)]
    generated_at: str
    files: list[TokensFileEntry]
    ext: dict[str, Any] | None = None


class SubmissionSidecar(RunManifest):
    """submission/<object_id>.sidecar.json: a RunManifest scoped to exactly one object (93 §3.9)."""

    command: str
    finished_at: str
    objects: Annotated[list[RunObject], Field(min_length=1, max_length=1)]


# ── Protocol (protocol.schema.json): Приложение 2 + Приложения А/Б/В ──────────────────────────


class ProtocolObject(_Strict):
    object_id: ObjectId
    name: str | None = None
    address: str | None = None
    supervision_case_no: str | None = None
    customer: str | None = None
    contractor: str | None = None


class ProtocolHeader(_Strict):
    title: Annotated[str, StringConstraints(pattern=r"^ПРОТОКОЛ АВТОМАТИЗИРОВАННОЙ СВЕРКИ № .+$")]
    generated_at_ru: str
    version_line: str
    status_line: str
    scenario_line: str | None = None
    recheck_running: bool | None = None


class UploadStatus(_Strict):
    pd: StageUploadStatus | None = None
    rd: StageUploadStatus | None = None
    id: StageUploadStatus | None = None


class LoadStatusRow(_Strict):
    stage: DocStage
    stage_ru: Literal["ПД", "РД", "ИД"]
    status: StageUploadStatus
    status_ru: str
    files_loaded: Annotated[int, Field(ge=0)]
    files_loaded_text: str
    files_expected: Annotated[int, Field(ge=0)] | None = None
    comment: str


class SummaryRow(_Strict):
    key: ProtocolSummaryRow
    label_ru: str
    count: Annotated[int, Field(ge=0)]
    percent: Annotated[float, Field(ge=0, le=100)]
    percent_text: Annotated[str, StringConstraints(pattern=r"^[0-9]{1,3}(,[0-9])?%$")]


class NotCheckedRow(_Strict):
    no: Annotated[int, Field(ge=1)]
    parameter_code: CanonicalParameterCode
    parameter_id: ParamId | None = None
    section_ru: str
    parameter_name: str
    missing_document: str


class Deviation(_Strict):
    direction: DeviationDirection | None = None
    text: str
    magnitude: float | None = None
    unit: str | None = None


InspectorDecisionRu = Literal["⏳ Ожидает", "✅ Подтверждено", "❌ Отклонено", "❓ Требует уточнения"]


class ViolationRow(_Strict):
    no: Annotated[int, Field(ge=1)]
    section_ru: str
    parameter_label: str
    parameter_code: SubmissionParameterCode
    parameter_id: ParamId | None = None
    matrix_scope: MatrixScope | None = None
    locations: list[Location] | None = None
    pd: str
    rd: str
    id: str
    deviation: Deviation
    inspector_status: InspectorStatus
    inspector_decision_ru: InspectorDecisionRu
    card_ref: CardNo
    finding_group_id: str | None = None
    finding_ids: list[Annotated[str, StringConstraints(min_length=1)]] | None = None
    criticality_level: CriticalityLevel | None = None


class SuspicionRow(_Strict):
    no: Annotated[int, Field(ge=1)]
    method: DiscoveryMethod
    method_ru: str
    description: str
    pd: str
    rd: str
    id: str
    parameter_code: FreeParameterCode | None = None
    inspector_status: SuspicionInspectorStatus
    inspector_decision_ru: str
    rejection_reason: str
    ai_comment: str
    confidence: Confidence | None = None
    card_ref: CardNo
    finding_group_id: str | None = None


class ResolutionCriticalRow(_Strict):
    no: Annotated[int, Field(ge=1)]
    work_type: str
    recommendation: str
    parameter_code: SubmissionParameterCode | None = None
    is_draft: bool | None = None
    text_origin: TextOrigin | None = None
    template_id: str | None = None
    source_row_no: Annotated[int, Field(ge=1)] | None = None


class ResolutionSubstantialRow(_Strict):
    no: Annotated[int, Field(ge=1)]
    violation_kind: str
    recommendation: str
    parameter_code: SubmissionParameterCode | None = None
    is_draft: bool | None = None
    text_origin: TextOrigin | None = None
    template_id: str | None = None
    source_row_no: Annotated[int, Field(ge=1)] | None = None


class Section1(_Strict):
    rows: list[LoadStatusRow]
    scenario_line: str | None = None


class Section2(_Strict):
    rows: list[SummaryRow]
    footnotes: list[str] | None = None


class Section3(_Strict):
    count: Annotated[int, Field(ge=0)]
    rows: list[NotCheckedRow]


class ViolationSection(_Strict):
    count: Annotated[int, Field(ge=0)]
    rows: list[ViolationRow]


class Section6(_Strict):
    count: Annotated[int, Field(ge=0)]
    rows: list[SuspicionRow]


class Section7(_Strict):
    critical: list[ResolutionCriticalRow]
    substantial: list[ResolutionSubstantialRow]


class Appendix2(_Strict):
    section1_load_status: Section1
    section2_summary: Section2
    section3_not_checked_no_id: Section3
    section4_critical: ViolationSection
    section5_substantial: ViolationSection
    section6_ai_suspicions: Section6
    section7_resolution: Section7
    footnotes: list[str] | None = None


class CompletenessRow(_Strict):
    parameter_code: CanonicalParameterCode
    parameter_name: str
    section_ru: str | None = None
    protocol_status: ProtocolParamStatus
    completeness_status: CompletenessStatus | None = None
    completeness_basis: CompletenessBasis | None = None
    missing_stage: DocStage | None = None
    document: str | None = None
    reason_ru: str | None = None
    action_ru: str | None = None


class CandidateRow(_Strict):
    card_ref: CardNo
    finding_group_id: str | None = None
    finding_ids: list[Annotated[str, StringConstraints(min_length=1)]] | None = None
    parameter_code: SubmissionParameterCode
    parameter_label: str
    locations: list[Location] | None = None
    expected: StageValue = None
    actual: StageValue = None
    deviation_text: str | None = None
    criticality_level: CriticalityLevel | None = None
    risk_level: RiskLevel | None = None
    confidence: Confidence | None = None
    inspector_status: InspectorStatus
    basis_code: DecisionConfirmBasis | None = None
    clarify_code: DecisionClarifyBasis | None = None
    comment: str | None = None
    decided_at: str | None = None


class NegativeRow(_Strict):
    card_ref: CardNo | None = None
    parameter_code: SubmissionParameterCode
    parameter_label: str
    locations: list[Location] | None = None
    decided_by: DecidedBy
    reason_code: DecisionRejectReason | None = None
    reason_ru: str | None = None
    comment: str | None = None
    ai_comment: str | None = None
    decided_at: str | None = None


class HypothesisRow(_Strict):
    card_ref: CardNo
    finding_group_id: str | None = None
    parameter_code: FreeParameterCode | None = None
    method: DiscoveryMethod
    description: str
    confidence: Confidence | None = None
    normative_base: str | None = None
    evidence_bind_status: EvidenceBindStatus | None = None
    inspector_status: SuspicionInspectorStatus


class Tz92Tables(_Strict):
    a1_completeness: list[CompletenessRow] | None = None
    a2_candidates: list[CandidateRow] | None = None
    a3_confirmed: list[CandidateRow] | None = None
    a4_negative_verified: list[NegativeRow] | None = None
    a5_hypotheses: list[HypothesisRow] | None = None
    banner_ru: str | None = None


class CardSource(_Strict):
    role: EvidenceRole | None = None
    stage: DocStage
    file_id: CitableFileId
    file_name: str | None = None
    file_sha256: Sha256 | None = None
    document_code: str | None = None
    revision: str | None = None
    approval_status: ApprovalStatus | None = None
    approval_date: str | None = None
    pdf_page_number: PageNumber
    sheet_number: SheetNumber = None
    geometry: Geometry | None = None
    geometry_space: GeometrySpace | None = None
    thumbnail: str | None = None
    value_text: str | None = None


class CardInspector(_Strict):
    status: InspectorStatus
    reason_code: DecisionRejectReason | None = None
    basis_code: DecisionConfirmBasis | None = None
    clarify_code: DecisionClarifyBasis | None = None
    comment: str | None = None
    user_id: str | None = None
    decided_at: str | None = None


class EvidenceCard(_Strict):
    card_no: CardNo
    finding_group_id: str | None = None
    finding_ids: list[Annotated[str, StringConstraints(min_length=1)]] | None = None
    parameter_code: SubmissionParameterCode
    parameter_label: str
    rule_version: str | None = None
    locations: list[Location]
    expected_value: StageValue = None
    actual_value: StageValue = None
    delta: dict[str, Any] | None = None
    rationale: str | None = None
    risk_level: RiskLevel | None = None
    review_priority: ReviewPriority | None = None
    criticality: CriticalityString | None = None
    approved_change_ref: str | None = None
    sources: Annotated[list[CardSource], Field(min_length=1)]
    inspector: CardInspector
    ai_verdict: AiVerdict | None = None
    ai_comment: str | None = None
    stage_values: dict[Literal["PD", "RD", "ID"], str | None] | None = None


class RegistryRow(_Strict):
    file_id: FileId
    file_name: str | None = None
    stage: DocStage | None
    manifest_stage: ManifestStage | None = None
    section: str | None = None
    document_code: str | None = None
    revision: str | None = None
    approval_status: ApprovalStatus | None = None
    pages: Annotated[int, Field(ge=0)] | None = None
    sha256: Sha256
    local_status: LocalFileStatus | None = None
    used: bool
    exclusion_reason: str | None = None


class InputRegistry(_Strict):
    files: list[RegistryRow]
    parser_versions: dict[str, str] | None = None


class Signature(_Strict):
    inspector_name: str | None = None
    inspector_position: str | None = None
    signed_at: str | None = None
    finalized_at: str | None = None
    finalized_by: str | None = None
    content_sha256: Sha256 | None = None


class Protocol(_Strict):
    """runs/<run_id>/protocol/<object_id>.json: Приложение 2 verbatim + Приложения А/Б/В (AG-04)."""

    schema_version: Literal[1] = 1
    protocol_no: Annotated[str, StringConstraints(min_length=1)]
    run_id: str | None = None
    object: ProtocolObject
    version: Annotated[int, Field(ge=1)]
    is_final: bool
    status: ProtocolStatus
    process_status: ProcessStatus | None = None
    generated_at: str
    scenario: LoadScenario
    scenario_base: ScenarioBase | None = None
    upload_status: UploadStatus | None = None
    versions: Versions
    input_manifest_hash: Sha256
    content_sha256: Sha256 | None = None
    header: ProtocolHeader
    appendix2: Appendix2
    tz92_tables: Tz92Tables
    evidence_cards: list[EvidenceCard]
    input_registry: InputRegistry
    signature: Signature | None = None
    submission_checks: list[SubmissionCheck] | None = None
    ext: dict[str, Any] | None = None


# Model ↔ schema registry used by the drift tests: (model, schema name, JSON pointer to the object schema).
MODEL_SCHEMAS: list[tuple[type[BaseModel], str, str]] = [
    (EvidenceRef, "evidence_ref", ""),
    (Finding, "finding", ""),
    (PageTokens, "page_tokens", ""),
    (PageInfo, "page_tokens", "/properties/page"),
    (Token, "page_tokens", "/$defs/Token"),
    (Line, "page_tokens", "/$defs/Line"),
    (Zone, "page_tokens", "/$defs/Zone"),
    (ExtractedValue, "extracted_value", ""),
    (ValueNorm, "extracted_value", "/properties/value_norm"),
    (RunManifest, "run_manifest", ""),
    (RunObject, "run_manifest", "/$defs/ObjectEntry"),
    (RunFile, "run_manifest", "/$defs/FileEntry"),
    (RunInputs, "run_manifest", "/properties/inputs"),
    (HostInfo, "run_manifest", "/properties/host"),
    (ObjectArtifacts, "run_manifest", "/$defs/ObjectEntry/properties/artifacts"),
    (Versions, "common", "/$defs/Versions"),
    (Geometry, "common", "/$defs/Geometry"),
    (SubmissionCheck, "submission.extended", "/$defs/Check"),
    (ManifestRow, "manifest_row", ""),
    (CatalogRow, "catalog_row", ""),
    (GoldCheck, "gold_check", ""),
    (GoldEvidence, "gold_check", "/$defs/GoldEvidence"),
    (GoldGroup, "gold_group", ""),
    (FindingGroup, "finding_group", ""),
    (Recommendation, "finding_group", "/$defs/Recommendation"),
    (Decision, "decision", ""),
    (LayoutArtifacts, "layout_artifacts", ""),
    (LayoutProvenance, "layout_artifacts", "/$defs/Provenance"),
    (ChangeRow, "layout_artifacts", "/$defs/ChangeRow"),
    (TitleBlock, "layout_artifacts", "/$defs/TitleBlock"),
    (SheetPageEntry, "layout_artifacts", "/$defs/SheetPageEntry"),
    (RoomEntry, "layout_artifacts", "/$defs/RoomEntry"),
    (TagInstance, "layout_artifacts", "/$defs/TagInstance"),
    (CadLayer, "layout_artifacts", "/$defs/CadLayer"),
    (RevisionCloud, "layout_artifacts", "/$defs/RevisionCloud"),
    (QrLink, "layout_artifacts", "/$defs/QrLink"),
    (TableArtifacts, "table_artifacts", ""),
    (TypedTable, "table_artifacts", "/$defs/TypedTable"),
    (PageBox, "table_artifacts", "/$defs/PageBox"),
    (TableColumn, "table_artifacts", "/$defs/Column"),
    (TableCell, "table_artifacts", "/$defs/Cell"),
    (TableRow, "table_artifacts", "/$defs/Row"),
    (TableCheck, "table_artifacts", "/$defs/Check"),
    (RunArtifacts, "run_artifacts", ""),
    (Artifact, "run_artifacts", "/$defs/Artifact"),
    (PageTokensDir, "run_artifacts", "/$defs/PageTokensDir"),
    (ArtifactProducer, "run_artifacts", "/$defs/Producer"),
    (TokensIndex, "tokens_index", ""),
    (TokensFileEntry, "tokens_index", "/$defs/FileEntry"),
    (TokensPageEntry, "tokens_index", "/$defs/PageEntry"),
    (Protocol, "protocol", ""),
    (ProtocolObject, "protocol", "/$defs/ProtocolObject"),
    (ProtocolHeader, "protocol", "/$defs/Header"),
    (UploadStatus, "protocol", "/properties/upload_status"),
    (Appendix2, "protocol", "/properties/appendix2"),
    (Section1, "protocol", "/properties/appendix2/properties/section1_load_status"),
    (Section2, "protocol", "/properties/appendix2/properties/section2_summary"),
    (Section3, "protocol", "/properties/appendix2/properties/section3_not_checked_no_id"),
    (ViolationSection, "protocol", "/properties/appendix2/properties/section4_critical"),
    (Section6, "protocol", "/properties/appendix2/properties/section6_ai_suspicions"),
    (Section7, "protocol", "/properties/appendix2/properties/section7_resolution"),
    (LoadStatusRow, "protocol", "/$defs/LoadStatusRow"),
    (SummaryRow, "protocol", "/$defs/SummaryRow"),
    (NotCheckedRow, "protocol", "/$defs/NotCheckedRow"),
    (Deviation, "protocol", "/$defs/Deviation"),
    (ViolationRow, "protocol", "/$defs/ViolationRow"),
    (SuspicionRow, "protocol", "/$defs/SuspicionRow"),
    (ResolutionCriticalRow, "protocol", "/$defs/ResolutionCriticalRow"),
    (ResolutionSubstantialRow, "protocol", "/$defs/ResolutionSubstantialRow"),
    (Tz92Tables, "protocol", "/properties/tz92_tables"),
    (CompletenessRow, "protocol", "/$defs/CompletenessRow"),
    (CandidateRow, "protocol", "/$defs/CandidateRow"),
    (NegativeRow, "protocol", "/$defs/NegativeRow"),
    (HypothesisRow, "protocol", "/$defs/HypothesisRow"),
    (EvidenceCard, "protocol", "/$defs/EvidenceCard"),
    (CardSource, "protocol", "/$defs/CardSource"),
    (CardInspector, "protocol", "/$defs/CardInspector"),
    (InputRegistry, "protocol", "/properties/input_registry"),
    (RegistryRow, "protocol", "/$defs/RegistryRow"),
    (Signature, "protocol", "/$defs/Signature"),
]

Finding.model_rebuild()
