"""Document decoding and normalization without mandatory third-party packages."""

from __future__ import annotations

import base64
import csv
import io
import json
import re
import zlib
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from .models import Document


TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".csv",
    ".tsv",
    ".json",
    ".xml",
    ".html",
    ".htm",
    ".yaml",
    ".yml",
    ".log",
}
MAX_ARCHIVE_ENTRIES = 10_000
MAX_ARCHIVE_MEMBER_BYTES = 50 * 1024 * 1024
MAX_ARCHIVE_EXPANDED_BYTES = 200 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200


def _validate_archive(archive: zipfile.ZipFile) -> None:
    entries = archive.infolist()
    if len(entries) > MAX_ARCHIVE_ENTRIES:
        raise ValueError("The Office file contains too many archive entries.")
    expanded = sum(entry.file_size for entry in entries)
    if expanded > MAX_ARCHIVE_EXPANDED_BYTES:
        raise ValueError("The Office file expands beyond the 200 MB extraction limit.")
    for entry in entries:
        if entry.file_size > MAX_ARCHIVE_MEMBER_BYTES:
            raise ValueError(f"The Office file contains an oversized component: {entry.filename}")
        if entry.compress_size and entry.file_size / entry.compress_size > MAX_COMPRESSION_RATIO:
            raise ValueError(f"The Office file contains a suspiciously compressed component: {entry.filename}")


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _xml_text(xml_data: bytes) -> str:
    root = ET.fromstring(xml_data)
    chunks: list[str] = []
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag in {"t", "instrText"} and element.text:
            chunks.append(element.text)
        elif tag in {"tab"}:
            chunks.append("\t")
        elif tag in {"br", "cr", "p", "tr"}:
            chunks.append("\n")
        elif tag == "tc":
            chunks.append(" | ")
    return "".join(chunks)


def _extract_docx(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        _validate_archive(archive)
        parts = []
        for name in (
            "word/document.xml",
            "word/footnotes.xml",
            "word/endnotes.xml",
            "word/comments.xml",
        ):
            if name in archive.namelist():
                parts.append(_xml_text(archive.read(name)))
        for name in sorted(n for n in archive.namelist() if n.startswith("word/header")):
            parts.append(_xml_text(archive.read(name)))
        for name in sorted(n for n in archive.namelist() if n.startswith("word/footer")):
            parts.append(_xml_text(archive.read(name)))
    return "\n".join(part for part in parts if part.strip())


def _xlsx_value(cell: ET.Element, shared: list[str], ns: dict[str, str]) -> str:
    value_node = cell.find("main:v", ns)
    inline = cell.find("main:is", ns)
    if inline is not None:
        return "".join(node.text or "" for node in inline.findall(".//main:t", ns))
    if value_node is None or value_node.text is None:
        return ""
    if cell.attrib.get("t") == "s":
        try:
            return shared[int(value_node.text)]
        except (ValueError, IndexError):
            return value_node.text
    return value_node.text


def _extract_xlsx(data: bytes) -> str:
    ns = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        _validate_archive(archive)
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall("main:si", ns):
                shared.append("".join(n.text or "" for n in item.findall(".//main:t", ns)))

        output: list[str] = []
        sheet_names = sorted(
            name
            for name in archive.namelist()
            if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)
        )
        for index, name in enumerate(sheet_names, start=1):
            output.append(f"[Worksheet {index}]")
            root = ET.fromstring(archive.read(name))
            for row in root.findall(".//main:row", ns):
                values = [_xlsx_value(cell, shared, ns) for cell in row.findall("main:c", ns)]
                output.append(" | ".join(values))
    return "\n".join(output)


def _unescape_pdf_literal(value: bytes) -> str:
    value = re.sub(rb"\\([nrtbf])", lambda match: {
        b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f"
    }[match.group(1)], value)
    value = re.sub(rb"\\([()\\])", rb"\1", value)
    value = re.sub(rb"\\([0-7]{1,3})", lambda match: bytes([int(match.group(1), 8) % 256]), value)
    return _decode_text(value)


def _pdf_stream_text(stream: bytes) -> list[str]:
    fragments: list[str] = []
    for match in re.finditer(rb"\((?:\\.|[^\\()])*\)\s*Tj", stream, re.S):
        literal = match.group(0).rsplit(b")", 1)[0][1:]
        fragments.append(_unescape_pdf_literal(literal))
    for array_match in re.finditer(rb"\[(.*?)\]\s*TJ", stream, re.S):
        items = re.findall(rb"\((?:\\.|[^\\()])*\)", array_match.group(1), re.S)
        if items:
            fragments.append("".join(_unescape_pdf_literal(item[1:-1]) for item in items))
    return fragments


def _extract_pdf(data: bytes) -> tuple[str, list[str]]:
    warnings: list[str] = []
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages), warnings
    except ImportError:
        pass
    except Exception as exc:  # pragma: no cover - dependent on malformed third-party inputs
        warnings.append(f"Primary PDF extraction failed: {exc}")

    fragments = _pdf_stream_text(data)
    for stream_match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        raw = stream_match.group(1)
        candidates = [raw]
        try:
            candidates.insert(0, zlib.decompress(raw))
        except zlib.error:
            pass
        for candidate in candidates:
            fragments.extend(_pdf_stream_text(candidate))

    text = "\n".join(fragment.strip() for fragment in fragments if fragment.strip())
    if not text:
        warnings.append(
            "OCR required: no machine-readable PDF text was found. Provide an OCR-enabled PDF; this document was not treated as reviewed evidence."
        )
    else:
        warnings.append("PDF was read with the built-in fallback extractor; verify complex tables and encoded text.")
    return text, warnings


def decode_upload(item: dict[str, Any], index: int) -> Document:
    name = Path(str(item.get("name") or f"document-{index}.txt")).name
    encoding = item.get("encoding", "text")
    raw_content = item.get("content", "")
    if encoding == "base64":
        try:
            data = base64.b64decode(raw_content, validate=True)
        except (ValueError, TypeError) as exc:
            return Document(
                id=f"DOC-{index:03d}",
                name=name,
                text="",
                extraction_status="Failed",
                warnings=[f"Invalid base64 upload: {exc}"],
            )
    else:
        data = str(raw_content).encode("utf-8")

    extension = Path(name).suffix.lower()
    warnings: list[str] = []
    status = "Complete"
    try:
        if extension in TEXT_EXTENSIONS or not extension:
            text = _decode_text(data)
        elif extension == ".docx":
            text = _extract_docx(data)
        elif extension in {".xlsx", ".xlsm"}:
            text = _extract_xlsx(data)
        elif extension == ".pdf":
            text, warnings = _extract_pdf(data)
            if warnings:
                status = "Partial" if text else "Failed"
        else:
            text = ""
            status = "Failed"
            warnings.append(
                f"Unsupported file type {extension or '(none)'}. Use PDF, DOCX, XLSX, CSV, JSON, XML, HTML, Markdown, or text."
            )
    except (zipfile.BadZipFile, ET.ParseError, KeyError, OSError, ValueError) as exc:
        text = ""
        status = "Failed"
        warnings.append(f"Document extraction failed: {exc}")

    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text).strip()
    return Document(
        id=f"DOC-{index:03d}",
        name=name,
        text=text,
        extraction_status=status,
        warnings=warnings,
    )


def parse_request_files(payload: dict[str, Any]) -> list[Document]:
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("Add at least one validation document before starting the review.")
    if len(files) > 75:
        raise ValueError("A package may contain at most 75 documents per review.")
    return [decode_upload(item, index) for index, item in enumerate(files, start=1)]
