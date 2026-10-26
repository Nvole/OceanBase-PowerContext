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
from pathlib import Path

from powercontext.builtin.artifacts.memory import MemoryCandidateRequest, MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    CaptureSource,
    GetMemoryEntryRequest,
    SubmitSourceObservation,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft
from powercontext.builtin.sources import ContentSource
from powercontext.sources import (
    SourceDefinitionRegistry,
    SourceObservation,
    manifest_for_definition,
    project_source_for_transport,
)
from powercontext.sources.pdf_pages import PDF_PAGE_SOURCE_DEFINITION, PDFPageInput, search_pdf_pages
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence


class _EvidencePipeline:
    async def extract(self, request: MemoryCandidateRequest, /) -> tuple[MemoryEntryInput, ...]:
        entries = []
        for source in request.sources:
            if isinstance(source, SourceObservation):
                text = TextEvidence.model_validate(source.projection(TEXT_EVIDENCE_PROJECTION_KEY)).content
            elif isinstance(source, ContentSource):
                text = source.content
            else:
                continue
            entries.append(MemoryEntryInput(kind="source-evidence", text=text, sources=(source,)))
        return tuple(entries)


def test_pdf_search_preserves_named_document_scope_and_filters_other_sources(tmp_path: Path) -> None:
    async def scenario() -> None:
        config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'search.db'}"))
        registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
        pages = [
            PDFPageInput(
                document_id="NEBULA_2022_10K",
                document_sha256="a" * 64,
                page_number=1,
                text="Commercial clients include national retailers. Annual revenue was 500.",
            ),
            PDFPageInput(
                document_id="3M_2018_10K",
                document_sha256="d" * 64,
                page_number=1,
                text="Industrial clients include local distributors. Annual revenue was 100.",
            ),
            PDFPageInput(
                document_id="3M_2023Q2_10Q",
                document_sha256="c" * 64,
                page_number=1,
                text="Industrial clients include regional distributors. Annual revenue was 300.",
            ),
            PDFPageInput(
                document_id="3M_1Q2022_10Q",
                document_sha256="e" * 64,
                page_number=1,
                text="Industrial clients include overseas distributors. Annual revenue was 200.",
            ),
            *(
                PDFPageInput(
                    document_id="ORION_CORPORATION_2022_10K",
                    document_sha256="b" * 64,
                    page_number=index,
                    text=(
                        "Trading Symbol Name of each exchange Common Stock ORIN New York Stock Exchange "
                        "Preferred Stock CASH New York Stock Exchange "
                        "Class B ON Nasdaq Exchange "
                        "Consolidated Balance Shee t Assets Cash 20 Inventory 50 "
                        "Property plant equipment net 500 Liabilities 100 Equity 470"
                        if index == 1
                        else "Consolidated Statements of Income Sales 600 Cost of goods sold 400 Income 200"
                        if index == 2
                        else f"Primary customers accounted for 80 percent of revenue. Customer disclosure {index}."
                    ),
                )
                for index in range(1, 25)
            ),
        ]
        async with open_builtin_runtime(config, candidate_pipeline=_EvidencePipeline()) as runtime:
            assert runtime.scopes is not None
            scope = await runtime.scopes.create(
                ScopeDraft(title="Reports", summary="Separate company evidence", idempotency_key="pdf-search")
            )
            await runtime.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
            for page in pages:
                source = await registry.resolve(page)
                await runtime.ingestion.submit(
                    SubmitSourceObservation(
                        scope_id=scope.scope_id, observation=project_source_for_transport(registry, source)
                    )
                )
            await runtime.sources.for_scope(scope.scope_id).capture(
                CaptureSource(
                    source_id="unrelated-note",
                    content="NEBULA_2022_10K\nPrimary customers accounted for 95 percent of revenue.",
                    metadata={},
                )
            )
            memory = runtime.memory.for_scope(scope.scope_id)
            while (await memory.flush()).processed:
                pass

        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope.scope_id)

            async def returned_labels(question: str, limit: int) -> list[str]:
                citations = await search_pdf_pages(memory, question, limit=limit)
                loaded = [await memory.get(GetMemoryEntryRequest(citation=citation)) for citation in citations]
                assert all(record.entry.sources[0].source_type == "pdf-page" for record in loaded)
                return [record.entry.text.partition("\n")[0] for record in loaded]

            named = await returned_labels("Who are Nebula's primary customers as of FY2022?", 20)
            assert named == ["NEBULA_2022_10K"]
            alphanumeric = await returned_labels("Who are 3M's primary customers as of Q2 FY2023?", 20)
            assert alphanumeric == ["3M_2023Q2_10Q"]
            both_periods = await returned_labels("What revenue did 3M report?", 3)
            assert set(both_periods) == {"3M_2018_10K", "3M_2023Q2_10Q", "3M_1Q2022_10Q"}
            ticker = await returned_labels("Who are $ORIN's primary customers?", 25)
            assert set(ticker) == {"ORION_CORPORATION_2022_10K"}
            explicit_ticker = await returned_labels("Who are $ON's primary customers?", 25)
            assert set(explicit_ticker) == {"ORION_CORPORATION_2022_10K"}
            comparison = await returned_labels("Compare the revenues of Nebula and Orion in 2022.", 25)
            assert set(comparison) == {"NEBULA_2022_10K", "ORION_CORPORATION_2022_10K"}
            unknown_alias = await returned_labels("Compare revenues of Nebula versus Northern Lights in 2022.", 28)
            expected_labels = {
                "NEBULA_2022_10K",
                "ORION_CORPORATION_2022_10K",
                "3M_2018_10K",
                "3M_2023Q2_10Q",
                "3M_1Q2022_10Q",
            }
            assert set(unknown_alias) == expected_labels
            unnamed = await returned_labels("What revenue was reported in 2022?", 28)
            assert set(unnamed) == expected_labels
            assert len(unnamed) == 28
            natural_word = await returned_labels("What CASH and revenue were reported?", 28)
            assert set(natural_word) == set(unnamed)
            capitalized_stopword = await returned_labels("What return ON assets and revenue was reported?", 28)
            assert set(capitalized_stopword) == set(unnamed)
            balance_citations = await search_pdf_pages(memory, "What was Orion's net PPNE in 2022?", limit=1)
            balance = await memory.get(GetMemoryEntryRequest(citation=balance_citations[0]))
            assert "Consolidated Balance Shee t" in balance.entry.text
            ratio_citations = await search_pdf_pages(memory, "What was Orion's inventory turnover?", limit=2)
            ratio_pages = [await memory.get(GetMemoryEntryRequest(citation=citation)) for citation in ratio_citations]
            assert any("Balance Shee t" in record.entry.text for record in ratio_pages)
            assert any("Statements of Income" in record.entry.text for record in ratio_pages)

    asyncio.run(scenario())
