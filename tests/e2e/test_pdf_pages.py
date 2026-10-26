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
import io
import re
from collections import Counter
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

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
