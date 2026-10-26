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

from __future__ import annotations

import asyncio
import base64
import io
import logging
import re
import zlib
from collections import Counter
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, EncodedStreamObject, NameObject

from powercontext.builtin.artifacts.memory import MemoryCandidateRequest, MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    GetMemoryEntryRequest,
    SubmitSourceObservation,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import (
    SourceDefinitionRegistry,
    SourceObservation,
    manifest_for_definition,
    project_source_for_transport,
)
from powercontext.sources.pdf_pages import (
    PDF_PAGE_SOURCE_DEFINITION,
    PDFDocumentInput,
    parse_pdf_document,
    search_pdf_pages,
)
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence


def _dense_pdf() -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=1000, height=2000)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
    })
    lines = ["BT /F1 8 Tf 40 1950 Td"]
    for index in range(160):
        text = f"Financial row {index}: revenue 123456 expenses 34567 assets 89012 liabilities 45678."
        lines.append(f"({text}) Tj 0 -11 Td")
    lines.extend(["(Terminalevidence annual liability 987654321) Tj", "ET"])
    stream = DecodedStreamObject()
    stream.set_data("\n".join(lines).encode("ascii"))
    page[NameObject("/Contents")] = stream
    writer.add_blank_page(width=100, height=100)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class _EvidencePipeline:
    async def extract(self, request: MemoryCandidateRequest, /) -> tuple[MemoryEntryInput, ...]:
        return tuple(
            MemoryEntryInput(
                kind="source-evidence",
                text=TextEvidence.model_validate(source.projection(TEXT_EVIDENCE_PROJECTION_KEY)).content,
                sources=(source,),
            )
            for source in request.sources
            if isinstance(source, SourceObservation)
        )


def test_pdf_long_page_retains_all_tokens_and_the_final_evidence() -> None:
    raw = _dense_pdf()
    extracted = PdfReader(io.BytesIO(raw)).pages[0].extract_text()
    pages = parse_pdf_document(PDFDocumentInput(document_id="dense-report", content=raw))
    assert [page.page_number for page in pages] == [1, 2]
    assert len(pages[0].text.encode()) > 8192
    assert Counter(re.findall(r"[a-z]+|\d+", pages[0].text.lower())) == Counter(
        re.findall(r"[a-z]+|\d+", extracted.lower())
    )
    assert pages[0].text.endswith("Terminalevidence annual liability 987654321")
    assert pages[1].text == ""


def _pdf_with_compressed_second_page(*, damage: str | None = None, form: bool = False) -> bytes:
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(_dense_pdf())))
    page = writer.pages[1]
    resources = writer.pages[0]["/Resources"]
    stream = EncodedStreamObject()
    compressed = zlib.compress(b"BT /F1 12 Tf 10 100 Td (Second page evidence) Tj ET")
    if damage == "truncated":
        compressed = compressed[:-4]
    elif damage == "broken":
        compressed = b"broken compressed content"
    stream._data = base64.a85encode(compressed, adobe=True)
    stream[NameObject("/Filter")] = ArrayObject([NameObject("/ASCII85Decode"), NameObject("/FlateDecode")])
    page[NameObject("/Resources")] = resources
    if form:
        stream[NameObject("/Type")] = NameObject("/XObject")
        stream[NameObject("/Subtype")] = NameObject("/Form")
        stream[NameObject("/Resources")] = resources
        xobjects = DictionaryObject()
        if damage != "missing-form":
            xobjects[NameObject("/Evidence")] = writer._add_object(stream)
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/XObject"): xobjects})
        invocation = DecodedStreamObject()
        invocation.set_data(b"/Evidence Do")
        page[NameObject("/Contents")] = writer._add_object(invocation)
    else:
        page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.mark.parametrize("form", [False, True])
def test_pdf_compressed_page_and_form_keep_all_text(form: bool) -> None:
    raw = _pdf_with_compressed_second_page(form=form)
    pages = parse_pdf_document(PDFDocumentInput(document_id="compressed", content=raw))
    assert len(pages) == 2
    assert pages[0].text.endswith("Terminalevidence annual liability 987654321")
    assert pages[1].text == "Second page evidence"


@pytest.mark.parametrize("damage", ["broken", "truncated"])
@pytest.mark.parametrize("form", [False, True])
def test_pdf_damaged_page_or_form_fails_atomically(damage: str, form: bool) -> None:
    raw = _pdf_with_compressed_second_page(damage=damage, form=form)
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="damaged", content=raw))


def test_pdf_missing_called_form_fails_atomically() -> None:
    raw = _pdf_with_compressed_second_page(damage="missing-form", form=True)
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="missing-form", content=raw))


def test_pdf_contents_array_is_one_program_across_stream_boundaries() -> None:
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(_dense_pdf())))
    page = writer.pages[1]
    page[NameObject("/Resources")] = writer.pages[0]["/Resources"]
    parts = ArrayObject()
    for content in (b"BT /F1 12 Tf 20 100 Td (Hello", b"text 12345) Tj ET"):
        stream = DecodedStreamObject()
        stream.set_data(content)
        parts.append(writer._add_object(stream.flate_encode()))
    page[NameObject("/Contents")] = parts
    buffer = io.BytesIO()
    writer.write(buffer)
    raw = buffer.getvalue()
    expected = PdfReader(io.BytesIO(raw)).pages[1].extract_text()
    pages = parse_pdf_document(PDFDocumentInput(document_id="content-array", content=raw))
    assert len(pages) == 2
    assert pages[1].text == " ".join(expected.split()) == "Hello text 12345"


def _pdf_with_form_calls(*, cyclic: bool) -> bytes:
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(_dense_pdf())))
    page = writer.pages[1]
    resources = writer.pages[0]["/Resources"]
    assert isinstance(resources, DictionaryObject)
    form = DecodedStreamObject()
    form.set_data(b"BT /F1 12 Tf 10 100 Td (Repeated evidence) Tj ET" + (b" /Self Do" if cyclic else b""))
    form[NameObject("/Subtype")] = NameObject("/Form")
    form_resources = DictionaryObject({NameObject("/Font"): resources["/Font"]})
    form[NameObject("/Resources")] = form_resources
    reference = writer._add_object(form)
    if cyclic:
        form_resources[NameObject("/XObject")] = DictionaryObject({NameObject("/Self"): reference})
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/XObject"): DictionaryObject({NameObject("/Evidence"): reference}),
    })
    invocation = DecodedStreamObject()
    invocation.set_data(b"/Evidence Do" if cyclic else b"/Evidence Do /Evidence Do")
    page[NameObject("/Contents")] = writer._add_object(invocation)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_pdf_repeated_form_calls_preserve_each_call() -> None:
    pages = parse_pdf_document(
        PDFDocumentInput(document_id="repeated-form", content=_pdf_with_form_calls(cyclic=False))
    )
    assert len(pages) == 2
    assert pages[1].text == "Repeated evidence Repeated evidence"


@pytest.mark.parametrize("level", [logging.WARNING, logging.ERROR])
def test_pdf_cyclic_form_fails_even_when_warnings_are_silent(caplog: pytest.LogCaptureFixture, level: int) -> None:
    raw = _pdf_with_form_calls(cyclic=True)
    with caplog.at_level(level, logger="pypdf"), pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="cyclic-form", content=raw))


def test_pdf_long_page_persists_and_retrieves_exact_evidence_after_restart(tmp_path: Path) -> None:
    async def scenario() -> None:
        page = parse_pdf_document(PDFDocumentInput(document_id="dense-report", content=_dense_pdf()))[0]
        registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
        source = await registry.resolve(page)
        observation = project_source_for_transport(registry, source)
        expected = f"{page.document_id}\n{page.text}"
        config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'pdf.db'}"))
        async with open_builtin_runtime(config, candidate_pipeline=_EvidencePipeline()) as runtime:
            assert runtime.scopes is not None
            scope = await runtime.scopes.create(
                ScopeDraft(title="PDF", summary="Complete evidence", idempotency_key="pdf-long-page")
            )
            await runtime.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
            request = SubmitSourceObservation(scope_id=scope.scope_id, observation=observation)
            await runtime.ingestion.submit(request)
            await runtime.ingestion.submit(request)
            memory = runtime.memory.for_scope(scope.scope_id)
            while (await memory.flush()).processed:
                pass

        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope.scope_id)
            records = await memory.list()
            assert len(records.entries) == 1
            assert records.entries[0].entry.text == expected
            citations = await search_pdf_pages(memory, "Terminalevidence annual liability", limit=1)
            assert len(citations) == 1
            loaded = await memory.get(GetMemoryEntryRequest(citation=citations[0]))
            assert loaded.entry.text == expected
            assert loaded.entry.sources[0].source_type == "pdf-page"
            assert loaded.entry.sources[0].source_id == source.name
            assert await registry.read(source) == page

    asyncio.run(scenario())
