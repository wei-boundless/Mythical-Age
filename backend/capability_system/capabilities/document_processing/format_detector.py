from __future__ import annotations

import zipfile
from pathlib import Path

from knowledge_system.conversion.models import SourceFileRecord

from capability_system.capabilities.document_processing.models import DetectedDocumentFormat, DocumentDiagnostic

_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_PDF_MAGIC = b"%PDF-"
_TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".rst", ".html", ".htm", ".xml", ".yaml", ".yml"}
_DATA_EXTENSIONS = {".csv", ".tsv", ".json", ".jsonl", ".ndjson"}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
_WORD_EXTENSIONS = {".doc", ".docx", ".docm", ".dot", ".dotx", ".dotm", ".rtf"}
_EXCEL_EXTENSIONS = {".xls", ".xlsx", ".xlsm", ".xlsb", ".xlt", ".xltx", ".xltm"}
_POWERPOINT_EXTENSIONS = {".ppt", ".pptx", ".pptm", ".pot", ".potx", ".potm", ".pps", ".ppsx", ".ppsm"}


class DocumentFormatDetector:
    def detect(self, record: SourceFileRecord) -> tuple[DetectedDocumentFormat, tuple[DocumentDiagnostic, ...]]:
        path = record.absolute_path
        extension = path.suffix.lower()
        declared_type = str(record.source_type or "").lower()
        diagnostics: list[DocumentDiagnostic] = []
        try:
            with path.open("rb") as handle:
                prefix = handle.read(8192)
        except OSError as exc:
            return (
                DetectedDocumentFormat(
                    family="unknown",
                    container="unknown",
                    extension=extension,
                    confidence=0.0,
                    signals=("read_failed",),
                    limitations=("file_not_readable",),
                    declared_type=declared_type,
                ),
                (
                    DocumentDiagnostic(
                        code="format_detection_read_failed",
                        severity="error",
                        message="Document format detection could not read the source file.",
                        details={"path": str(path), "error": str(exc)},
                    ),
                ),
            )

        if prefix.startswith(_PDF_MAGIC):
            detected = self._detected("pdf", "pdf", extension, 0.99, ("magic:%PDF-",), declared_type)
            diagnostics.extend(self._extension_conflict_diagnostics(detected))
            return detected, tuple(diagnostics)

        if prefix.startswith(_OLE_MAGIC):
            detected = self._detect_ole(extension, declared_type)
            diagnostics.extend(self._extension_conflict_diagnostics(detected))
            if detected.family == "unknown":
                diagnostics.append(
                    DocumentDiagnostic(
                        code="ole_family_unknown",
                        severity="warning",
                        message="Legacy Office container was detected, but the extension does not identify the family.",
                        details={"extension": extension, "source_path": record.source_path},
                    )
                )
            return detected, tuple(diagnostics)

        zip_entries = self._zip_entries(path, prefix)
        if zip_entries:
            detected = self._detect_ooxml(zip_entries, extension, declared_type)
            diagnostics.extend(self._extension_conflict_diagnostics(detected))
            return detected, tuple(diagnostics)

        detected = self._detect_by_extension(extension, declared_type)
        diagnostics.extend(self._extension_conflict_diagnostics(detected))
        if detected.family == "unknown":
            diagnostics.append(
                DocumentDiagnostic(
                    code="format_detection_low_confidence",
                    severity="warning",
                    message="Document format detection only found weak or unknown signals.",
                    details={"extension": extension, "source_path": record.source_path},
                )
            )
        return detected, tuple(diagnostics)

    def _detect_ooxml(
        self,
        entries: frozenset[str],
        extension: str,
        declared_type: str,
    ) -> DetectedDocumentFormat:
        signals = ["container:zip"]
        limitations: list[str] = []
        has_content_types = "[Content_Types].xml" in entries
        if has_content_types:
            signals.append("ooxml:[Content_Types].xml")
        if "word/document.xml" in entries:
            return self._detected("word", "ooxml", extension, 0.98, tuple(signals + ["ooxml:word/document.xml"]), declared_type)
        if "xl/workbook.xml" in entries:
            return self._detected("excel", "ooxml", extension, 0.98, tuple(signals + ["ooxml:xl/workbook.xml"]), declared_type)
        if "ppt/presentation.xml" in entries:
            return self._detected(
                "powerpoint",
                "ooxml",
                extension,
                0.98,
                tuple(signals + ["ooxml:ppt/presentation.xml"]),
                declared_type,
            )
        if has_content_types:
            limitations.append("ooxml_family_not_identified")
            return self._detected("unknown", "ooxml", extension, 0.65, tuple(signals), declared_type, tuple(limitations))
        return self._detect_by_extension(extension, declared_type, container="zip", confidence=0.45, signals=tuple(signals))

    def _detect_ole(self, extension: str, declared_type: str) -> DetectedDocumentFormat:
        family = self._family_from_extension(extension)
        limitations = () if family != "unknown" else ("legacy_ole_family_requires_extension_signal",)
        return self._detected(
            family,
            "ole",
            extension,
            0.82 if family != "unknown" else 0.58,
            ("magic:ole_compound_file", f"extension:{extension}" if extension else "extension:missing"),
            declared_type,
            limitations,
        )

    def _detect_by_extension(
        self,
        extension: str,
        declared_type: str,
        *,
        container: str = "plain",
        confidence: float = 0.55,
        signals: tuple[str, ...] = (),
    ) -> DetectedDocumentFormat:
        family = self._family_from_extension(extension)
        active_signals = list(signals)
        if extension:
            active_signals.append(f"extension:{extension}")
        limitations = () if family != "unknown" else ("weak_extension_signal_only",)
        if extension in _DATA_EXTENSIONS:
            container = "text"
        if extension in _TEXT_EXTENSIONS:
            container = "text"
        if extension in _IMAGE_EXTENSIONS:
            container = "image"
        return self._detected(family, container, extension, confidence, tuple(active_signals), declared_type, limitations)

    def _family_from_extension(self, extension: str) -> str:
        if extension in _WORD_EXTENSIONS:
            return "word"
        if extension in _EXCEL_EXTENSIONS:
            return "excel"
        if extension in _POWERPOINT_EXTENSIONS:
            return "powerpoint"
        if extension == ".pdf":
            return "pdf"
        if extension in _DATA_EXTENSIONS:
            return "data"
        if extension in _TEXT_EXTENSIONS:
            return "text"
        if extension in _IMAGE_EXTENSIONS:
            return "image"
        return "unknown"

    def _zip_entries(self, path: Path, prefix: bytes) -> frozenset[str]:
        if not prefix.startswith(b"PK"):
            return frozenset()
        try:
            with zipfile.ZipFile(path) as archive:
                return frozenset(name.replace("\\", "/") for name in archive.namelist())
        except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile):
            return frozenset()

    def _extension_conflict_diagnostics(self, detected: DetectedDocumentFormat) -> tuple[DocumentDiagnostic, ...]:
        extension_family = self._family_from_extension(detected.extension)
        if extension_family in {"unknown", detected.family}:
            return ()
        if detected.family == "unknown":
            return ()
        return (
            DocumentDiagnostic(
                code="format_extension_conflict",
                severity="warning",
                message="Container or magic-byte detection disagrees with the filename extension.",
                details={
                    "detected_family": detected.family,
                    "extension_family": extension_family,
                    "extension": detected.extension,
                    "container": detected.container,
                },
            ),
        )

    def _detected(
        self,
        family: str,
        container: str,
        extension: str,
        confidence: float,
        signals: tuple[str, ...],
        declared_type: str,
        limitations: tuple[str, ...] = (),
    ) -> DetectedDocumentFormat:
        return DetectedDocumentFormat(
            family=family,
            container=container,
            extension=extension,
            confidence=max(0.0, min(float(confidence), 1.0)),
            signals=signals,
            limitations=limitations,
            declared_type=declared_type,
        )
