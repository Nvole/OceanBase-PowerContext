# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Row-level CSV capture with stable document and primary-key identity."""

from __future__ import annotations

import csv
import io
import json
from urllib.parse import quote

from pydantic import BaseModel

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import (
    TEXT_EVIDENCE_PROJECTION_KEY,
    AdapterSourceDefinition,
    Source,
    SourceDefinition,
    SourceMaterialization,
    TextEvidence,
)

CSV_ROW_SOURCE_NAME = "csv-row"
_SOURCE_VERSION = "1"


class CSVDocumentInput(BaseModel):
    """One complete offline CSV document addressed by a caller-stable id."""

    document_id: str
    primary_key: str
    content: bytes


class CSVRowInput(BaseModel):
    """One validated data row, with header order and original field text."""

    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]


class CSVRowSource(Source):
    """Captured row whose identity is the document id plus the primary key value."""

    source_id: str
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]


def csv_row_source_id(document_id: str, primary_key_value: str) -> str:
    """Return ``csv:{quoted document}:{quoted key}``, bounded by the source id limit."""

    _require_document_id(document_id)
    _require_primary_key_value(primary_key_value)
    source_id = f"csv:{quote(document_id, safe='')}:{quote(primary_key_value, safe='')}"
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"source_id must not exceed {MAX_SOURCE_ID_LENGTH} characters")  # noqa: TRY003
    return source_id


def parse_csv_document(value: CSVDocumentInput) -> tuple[CSVRowInput, ...]:
    """Parse one UTF-8 CSV document into row inputs, or fail without partial rows."""

    document_id = _require_document_id(value.document_id)
    primary_key = _require_primary_key_name(value.primary_key)
    text = _decode_csv_text(value.content)
    records = _read_csv_records(text)
    columns, key_index = _header_columns(records, primary_key)
    return _data_rows(document_id, primary_key, columns, key_index, records[1:])


class CSVRowSourceAdapter:
    """Resolve one validated row into a captured source and read that row back."""

    input_class = CSVRowInput
    name = CSV_ROW_SOURCE_NAME
    source_class = CSVRowSource

    async def resolve(self, value: CSVRowInput, /) -> CSVRowSource:
        _validate_row(
            value.document_id,
            value.primary_key,
            value.primary_key_value,
            value.columns,
            value.values,
        )
        source_id = csv_row_source_id(value.document_id, value.primary_key_value)
        return CSVRowSource(
            name=source_id,
            definition_version=_SOURCE_VERSION,
            materialization=SourceMaterialization.CAPTURED,
            source_id=source_id,
            document_id=value.document_id,
            primary_key=value.primary_key,
            primary_key_value=value.primary_key_value,
            columns=value.columns,
            values=value.values,
        )

    async def read(self, source: CSVRowSource, /) -> CSVRowInput:
        return CSVRowInput(
            document_id=source.document_id,
            primary_key=source.primary_key,
            primary_key_value=source.primary_key_value,
            columns=source.columns,
            values=source.values,
        )


class CSVRowTextEvidenceProjection:
    """Project one captured row as ordered JSON text plus exact field metadata."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = CSVRowSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: CSVRowSource, /) -> TextEvidence:
        row = _row_object(source.columns, source.values)
        return TextEvidence(
            source_type=CSV_ROW_SOURCE_NAME,
            source_id=source.source_id,
            content=json.dumps(row, ensure_ascii=False, separators=(",", ":")),
            metadata={
                "document_id": source.document_id,
                "primary_key": source.primary_key,
                "primary_key_value": source.primary_key_value,
                "columns": list(source.columns),
                "row": row,
            },
        )


CSV_ROW_SOURCE_DEFINITION: SourceDefinition[CSVRowInput, CSVRowSource, CSVRowInput] = AdapterSourceDefinition(
    CSVRowSourceAdapter(),
    version=_SOURCE_VERSION,
    projections=(CSVRowTextEvidenceProjection(),),
)


def _require_document_id(document_id: object) -> str:
    if not isinstance(document_id, str) or not document_id or document_id != document_id.strip():
        raise ValueError("document_id must be non-empty and must not have surrounding whitespace")  # noqa: TRY003
    return document_id


def _require_primary_key_name(primary_key: object) -> str:
    if not isinstance(primary_key, str) or not primary_key:
        raise ValueError("primary_key must be non-empty")  # noqa: TRY003
    return primary_key


def _require_primary_key_value(primary_key_value: object) -> str:
    if not isinstance(primary_key_value, str) or not primary_key_value.strip():
        raise ValueError("primary key value must not be empty or whitespace")  # noqa: TRY003
    return primary_key_value


def _decode_csv_text(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("CSV content must be valid UTF-8") from error  # noqa: TRY003


def _read_csv_records(text: str) -> list[list[str]]:
    # newline="" keeps quoted CR-LF bytes intact; csv.reader applies strict quoting.
    try:
        return list(
            csv.reader(
                io.StringIO(text, newline=""),
                delimiter=",",
                quotechar='"',
                doublequote=True,
                escapechar=None,
                strict=True,
                skipinitialspace=False,
            )
        )
    except csv.Error as error:
        raise ValueError("malformed CSV") from error  # noqa: TRY003


def _header_columns(records: list[list[str]], primary_key: str) -> tuple[tuple[str, ...], int]:
    if not records:
        raise ValueError("CSV document must include a header")  # noqa: TRY003
    columns = tuple(records[0])
    if not columns or any(not column.strip() for column in columns):
        raise ValueError("header fields must be non-empty and not whitespace")  # noqa: TRY003
    if len(set(columns)) != len(columns):
        raise ValueError("header fields must be unique")  # noqa: TRY003
    try:
        key_index = columns.index(primary_key)
    except ValueError:
        raise ValueError("primary_key must exactly match a header field") from None  # noqa: TRY003
    return columns, key_index


def _data_rows(
    document_id: str,
    primary_key: str,
    columns: tuple[str, ...],
    key_index: int,
    records: list[list[str]],
) -> tuple[CSVRowInput, ...]:
    rows: list[CSVRowInput] = []
    seen: set[str] = set()
    for record in records:
        if not record:
            continue
        if len(record) != len(columns):
            raise ValueError("record width must match the header")  # noqa: TRY003
        values = tuple(record)
        primary_key_value = values[key_index]
        _require_primary_key_value(primary_key_value)
        if primary_key_value in seen:
            raise ValueError("primary key values must be unique")  # noqa: TRY003
        seen.add(primary_key_value)
        row = CSVRowInput(
            document_id=document_id,
            primary_key=primary_key,
            primary_key_value=primary_key_value,
            columns=columns,
            values=values,
        )
        _validate_row(document_id, primary_key, primary_key_value, columns, values)
        rows.append(row)
    return tuple(rows)


def _validate_row(
    document_id: str,
    primary_key: str,
    primary_key_value: str,
    columns: tuple[str, ...],
    values: tuple[str, ...],
) -> None:
    _require_document_id(document_id)
    _require_primary_key_name(primary_key)
    if not columns or any(not isinstance(column, str) or not column.strip() for column in columns):
        raise ValueError("columns must be non-empty and not whitespace")  # noqa: TRY003
    if len(set(columns)) != len(columns):
        raise ValueError("columns must be unique")  # noqa: TRY003
    if len(values) != len(columns) or any(not isinstance(item, str) for item in values):
        raise ValueError("values must be strings aligned with columns")  # noqa: TRY003
    try:
        key_index = columns.index(primary_key)
    except ValueError:
        raise ValueError("primary_key must exactly match a column") from None  # noqa: TRY003
    if values[key_index] != primary_key_value:
        raise ValueError("primary_key_value must exactly match the primary key column")  # noqa: TRY003
    csv_row_source_id(document_id, primary_key_value)


def _row_object(columns: tuple[str, ...], values: tuple[str, ...]) -> dict[str, str]:
    if len(columns) != len(values):
        raise ValueError("columns and values must have the same length")  # noqa: TRY003
    return dict(zip(columns, values, strict=True))


__all__ = [
    "CSV_ROW_SOURCE_DEFINITION",
    "CSV_ROW_SOURCE_NAME",
    "CSVDocumentInput",
    "CSVRowInput",
    "CSVRowSource",
    "csv_row_source_id",
    "parse_csv_document",
]
