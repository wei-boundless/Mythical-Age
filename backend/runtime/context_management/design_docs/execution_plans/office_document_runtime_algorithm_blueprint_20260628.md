# Office Document Runtime Algorithm Blueprint

Date: 2026-06-28

Integration note: this Office runtime is not an independent parsing authority. The target architecture places it under the unified `DocumentProcessingKernel`; see `document_processing_kernel_rag_office_integration_plan_20260628.md` for the RAG/Office integration flow.

## Objective

Build an algorithm-first office document capability layer for Word, Excel, PowerPoint, and PDF. The capability must not expose low-level libraries to the agent. The agent sees one document-processing role; the runtime owns detection, IR construction, patch planning, execution, verification, and artifact reporting.

The core pipeline is:

```text
OfficeDocumentRequest
  -> FormatDetector
  -> ResourceResolver
  -> IngestionAdapter
  -> OfficeDocumentIR
  -> IntentCompiler
  -> OperationPlanner
  -> PatchExecutor
  -> VerificationEngine
  -> ArtifactWriter
  -> OfficeDocumentResult
```

External resources such as LibreOffice, Pandoc, python-docx, openpyxl, python-pptx, pypdf, pdfplumber, pdftoppm, and OCR engines are execution resources only. They do not own routing, intent, edit planning, or success criteria.

## Non-Negotiable Design Rules

1. The runtime must protect source files. Editing defaults to copy-then-patch.
2. Each operation must produce a serializable patch plan before execution.
3. Adapter code must consume an explicit plan. It must not reinterpret the user request.
4. Result status cannot be `ok` unless detection, execution, and verification all pass.
5. Excel data analysis remains delegated to `structured-data-analysis`.
6. PDF deep reading remains delegated to `pdf-analysis`.
7. RAG remains knowledge lookup only; it must not become the Office edit path.
8. Legacy `.doc/.xls/.ppt` formats go through converter resources. Do not hand-roll fragile binary parsers.

## 1. Format Detection Algorithm

Input:

```text
path
declared_mime
user_declared_type
first_8192_bytes
zip_entries
```

Output:

```text
DetectedDocumentFormat
  family: word | excel | powerpoint | pdf | unknown
  container: ooxml | ole | pdf | unknown
  extension
  confidence
  signals
  limitations
```

Rules:

- PDF is identified by `%PDF-` magic bytes.
- OOXML is identified by ZIP container plus `[Content_Types].xml`.
- Word OOXML requires `word/document.xml`.
- Excel OOXML requires `xl/workbook.xml`.
- PowerPoint OOXML requires `ppt/presentation.xml`.
- Legacy Office OLE is identified by `D0 CF 11 E0 A1 B1 1A E1` magic bytes plus extension signal.
- Extension is weak evidence only. If extension conflicts with container evidence, container evidence wins and the conflict is recorded.

## 2. OfficeDocumentIR

The runtime normalizes all supported files into one intermediate representation:

```text
OfficeDocumentIR
  document_id
  source
  detected_format
  metadata
  parts
  blocks
  tables
  assets
  anchors
  styles
  layout
  lineage
  diagnostics
```

Core node models:

```text
DocumentPart
  part_id
  part_type: body | sheet | slide | page | header | footer | notes | comments
  name
  order
  location
  metadata

DocumentBlock
  block_id
  part_id
  block_type: paragraph | heading | list_item | text_box | cell | shape_text | pdf_text
  text
  normalized_text
  style_ref
  location
  anchors
  confidence
  metadata

DocumentTable
  table_id
  part_id
  location
  rows
  columns
  cells
  header_rows
  inferred_schema
  source_kind: word_table | excel_range | ppt_table | pdf_table

DocumentAnchor
  anchor_id
  anchor_type: structural | text_hash | title | range | bbox | object_id | semantic
  target_id
  value
  confidence
  stability
```

Locations use a shared schema with optional fields such as `page`, `slide_index`, `sheet_name`, `cell_ref`, `paragraph_index`, `shape_id`, `bbox`, `xml_path`, and `source_part`.

## 3. IR Construction Algorithms

### Word

Extract paragraphs, headings, lists, tables, headers, footers, footnotes, endnotes, images, hyperlinks, comments, styles, and relationship references.

Algorithm:

1. Traverse block-level nodes in `word/document.xml`.
2. Infer heading levels from paragraph style and numbering.
3. Build paragraph anchors from part id, paragraph index, normalized text hash, and heading path.
4. Expand tables into row/column/cell nodes while preserving merge metadata.
5. Map relationship ids to assets.
6. Preserve unknown OOXML parts as opaque references for write-back.

### Excel

Extract workbook metadata, sheets, hidden state, freeze panes, cell values, formulas, data types, styles, merged cells, named ranges, tables, charts, images, validation, and conditional-format references.

Algorithm:

1. Traverse workbook sheets.
2. Compute occupied ranges.
3. Cluster continuous non-empty blocks into candidate data regions.
4. Infer table headers and data column types.
5. Record formulas as formulas, not as recalculated values.
6. Generate stable anchors from `sheet!cell`, named range, table column, and row identity.
7. Delegate aggregation/filtering/ranking calculations to the existing structured-data capability.

### PowerPoint

Extract slides, shapes, text frames, tables, images, charts, speaker notes, layout/master references, bounding boxes, and z-order.

Algorithm:

1. Traverse slides in order.
2. Convert each shape into block, table, or asset nodes.
3. Extract text by paragraph/run, but use shape as the default edit unit.
4. Generate anchors from slide index, shape id, placeholder type, text hash, and bbox bucket.
5. Record animations and complex master information as limitations in the first implementation stage.

### PDF

Extract pages, text spans, bounding boxes, tables, images, OCR text, and OCR confidence.

Algorithm:

1. Prefer native text layer extraction.
2. Trigger OCR when text layer is absent or low quality.
3. Sort text spans by page, y bucket, and x coordinate.
4. Merge spans with close baseline and horizontal proximity.
5. Detect tables using available table extraction first, then fallback to x/y alignment clustering.
6. Treat PDF editing as page-level operations in stage one. Text content edits should happen on the source Office file when available.

## 4. Intent Compilation

Input:

```text
user_instruction
detected_format
OfficeDocumentIR summary
active task context
file permissions
```

Output:

```text
CompiledOfficeIntent
  action: inspect | read | convert | edit | create | render_verify
  target_file_type
  read_scope
  write_policy
  required_outputs
  constraints
  ambiguity
```

Routing rules:

- Excel filter/sort/group/top-N/extreme-record questions route to `structured-data-analysis`.
- PDF page/section/document deep reading routes to `pdf-analysis`.
- Office generation, editing, format conversion, and render verification route to `office_document_runtime`.
- Knowledge-base lookup routes to RAG.

## 5. Patch Planning

Patch plans are mandatory for write-like operations:

```text
OfficePatchPlan
  plan_id
  source_path
  output_path
  operations
  preconditions
  preservation_policy
  verification_contract
  risk_level
```

Operation shape:

```text
OfficePatchOperation
  op_id
  op_type
  target_anchor
  payload
  precondition
  expected_effect
  fallback_policy
```

Supported stage-one operations:

- Word: `replace_paragraph_text`, `insert_paragraph_after`, `insert_table_after`, `update_table_cell`, `append_section`, `replace_image`.
- Excel: `update_cell`, `update_range`, `append_rows`, `create_sheet`, `create_table`, `create_chart`, `apply_style`, `set_formula`.
- PowerPoint: `replace_shape_text`, `add_slide`, `insert_text_box`, `insert_table`, `replace_image`, `reorder_slide`.
- PDF: `split_pages`, `merge_pdfs`, `delete_pages`, `reorder_pages`, `add_watermark`, `render_pages`.

Planning rules:

- Copy source before edits.
- Prefer local patch over full rewrite.
- Reject destructive edits when anchor confidence is low.
- Every operation must declare expected effects for verification.

## 6. Anchor Resolution

Candidate score:

```text
score = exact_match * 0.40
      + structural_match * 0.25
      + semantic_match * 0.20
      + proximity_match * 0.10
      + recency_or_user_scope * 0.05
```

Default thresholds:

```text
execute_threshold = 0.78
clarify_threshold = 0.55
```

Resolution order:

1. Exact path anchors: paragraph index, sheet cell/range, slide shape id, PDF page/bbox.
2. Structural anchors: heading path, table id, named range, slide title.
3. Text anchors: normalized text hash or fuzzy text match.
4. If top candidates are close or below threshold, return ambiguity instead of editing.

## 7. Preservation Algorithm

OOXML write-back:

1. Treat `.docx/.xlsx/.pptx` as packages.
2. Modify only target XML parts.
3. Preserve unknown package parts and relationships.
4. Reopen the generated file after write-back.

Excel formulas:

- Write formulas as formulas.
- Do not claim formula recalculation unless a real recalculation resource was used.
- Mark `formula_recalculation_not_verified` when recalculation is unavailable.

PDF:

- Stage one supports page-level editing and overlays.
- For textual edits, prefer modifying source Word/Excel/PPT and exporting a new PDF.

## 8. Verification Algorithm

Verification levels:

```text
basic
  file exists, non-zero size, can reopen

structural
  page/sheet/slide/paragraph/object counts match expected effects

semantic
  expected text, cells, formulas, tables, image refs match expected effects

render
  export to PDF/PNG, check page count and non-blank render

strict
  structural + semantic + render with full report
```

Non-blank render check:

1. Read PNG dimensions.
2. Sample pixels.
3. Compute non-white/non-transparent ratio.
4. Mark `blank_render_detected` when the ratio is below `0.003`.

Status calculation:

```text
confidence = format_confidence * 0.20
           + extraction_confidence * 0.20
           + anchor_confidence * 0.20
           + execution_success * 0.20
           + verification_score * 0.20
```

Any hard failure prevents `ok`.

## 9. Result Contract

```text
OfficeDocumentResult
  ok
  status: ok | degraded | clarify | error
  action
  file_type
  source_path
  output_path
  artifact_refs
  summary
  extracted_content
  patch_plan_id
  verification_report
  diagnostics
  limitations
```

Common degraded reasons:

- `missing_runtime_resource`
- `unsupported_legacy_format_without_converter`
- `ambiguous_anchor`
- `format_conflict`
- `render_verification_failed`
- `formula_recalculation_not_verified`
- `opaque_content_preserved_but_not_editable`

## 10. Implementation Order

Stage A: algorithm kernel. This stage is implemented under
`capability_system.capabilities.document_processing`, not under a separate
Office-only parsing authority.

```text
backend/capability_system/capabilities/document_processing/models.py
backend/capability_system/capabilities/document_processing/format_detector.py
backend/capability_system/capabilities/document_processing/ir_builder.py
backend/capability_system/capabilities/document_processing/kernel.py
backend/capability_system/capabilities/office_document/models.py
backend/capability_system/capabilities/office_document/runtime.py
backend/capability_system/capabilities/office_document/planner.py
backend/capability_system/capabilities/office_document/executor.py
backend/capability_system/capabilities/office_document/verifier.py
```

Current implementation status:

- Stage-one copy-then-patch execution is connected for Word, Excel, PowerPoint, and PDF.
- Write requests use `DocumentProcessingKernel.parse(..., parse_profile="office_write")` so explicit patch operations do not trigger RAG/OCR parsing.
- Every write operation produces an `OfficePatchPlan`, an `OfficeExecutionReport`, and an `OfficeVerificationReport`.

Stage B: adapters.

```text
backend/capability_system/capabilities/office_document/adapters/word.py
backend/capability_system/capabilities/office_document/adapters/excel.py
backend/capability_system/capabilities/office_document/adapters/powerpoint.py
backend/capability_system/capabilities/office_document/adapters/pdf.py
```

Stage C: capability wiring.

```text
backend/capability_system/mcp/local_registry.py
backend/capability_system/mcp/server/server.py
backend/permissions/operations.py
backend/permissions/operation_packages.py
backend/task_system/environments/default_environments.py
backend/task_system/environments/prompt_resources.py
backend/agent_system/profiles/runtime_profile_registry.py
```

Stage D: physical validation, without adding regression test files.

- Generate docx, export PDF, render first page.
- Generate xlsx, inspect workbook, export PDF.
- Generate pptx, export PDF.
- Split/merge PDF, render pages.
- Confirm degraded diagnostics when a required runtime resource is missing.
