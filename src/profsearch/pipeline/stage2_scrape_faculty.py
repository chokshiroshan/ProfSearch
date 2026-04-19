"""Stage 2: scrape official roster sources into raw faculty candidates."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from profsearch.config import Settings
from profsearch.db.models import DepartmentSource, FacultyCandidate, University
from profsearch.pipeline.base import PipelineStage
from profsearch.scraping.client import AsyncHtmlClient
from profsearch.scraping.extractors import dedupe_entries, extract_pagination_urls, extract_profile_details, extract_roster_entries

PAGINATION_DISABLED_HINTS = {"princeton_content_list"}


@dataclass(slots=True)
class ScrapedPage:
    requested_url: str
    final_url: str
    status_code: int
    html_excerpt: str


@dataclass(slots=True)
class SourceScrapeResult:
    final_url: str
    entries: list
    error: str | None
    pages: list[ScrapedPage]


class Stage2ScrapeFaculty(PipelineStage):
    name = "stage2"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def _enrich_entry(self, client: AsyncHtmlClient, entry, approved_domains: set[str]):
        if not entry.profile_url or (entry.title and entry.email):
            return entry
        try:
            response = await client.fetch(entry.profile_url, approved_domains)
            details = extract_profile_details(response.text, response.url)
        except Exception:
            return entry
        if not details.title and not details.email:
            return entry
        return replace(
            entry,
            title=details.title or entry.title,
            email=details.email or entry.email,
            profile_text=details.profile_text or entry.profile_text,
            source_url=details.source_url if details.title else entry.source_url,
            source_snippet=details.source_snippet or entry.source_snippet,
        )

    async def _scrape_source(self, source: DepartmentSource, approved_domains: set[str]) -> SourceScrapeResult:
        client = AsyncHtmlClient(self.settings)
        pages: list[ScrapedPage] = []
        last_final_url = source.roster_url
        try:
            queue = [source.roster_url]
            seen_pages: set[str] = set()
            all_entries = []
            while queue:
                page_url = queue.pop(0)
                if page_url in seen_pages:
                    continue
                seen_pages.add(page_url)
                response = await client.fetch(page_url, approved_domains)
                last_final_url = response.url
                pages.append(
                    ScrapedPage(
                        requested_url=page_url,
                        final_url=response.url,
                        status_code=response.status_code,
                        html_excerpt=response.text[:4000],
                    )
                )
                all_entries.extend(extract_roster_entries(response.text, response.url, source.parser_hint))
                if source.parser_hint not in PAGINATION_DISABLED_HINTS:
                    for next_url in extract_pagination_urls(response.text, response.url):
                        if next_url not in seen_pages:
                            queue.append(next_url)
            deduped = dedupe_entries(all_entries)
            enriched = []
            for entry in deduped:
                enriched.append(await self._enrich_entry(client, entry, approved_domains))
            return SourceScrapeResult(
                final_url=last_final_url,
                entries=dedupe_entries(enriched),
                error=None,
                pages=pages,
            )
        except Exception as exc:
            return SourceScrapeResult(
                final_url=last_final_url,
                entries=[],
                error=str(exc),
                pages=pages,
            )
        finally:
            await client.aclose()

    def _upsert_candidate(self, session: Session, source: DepartmentSource, university: University, entry) -> None:
        existing = None
        if entry.profile_url:
            existing = session.scalar(
                select(FacultyCandidate).where(
                    FacultyCandidate.department_source_id == source.id,
                    FacultyCandidate.profile_url == entry.profile_url,
                )
            )
        if not existing:
            existing = session.scalar(
                select(FacultyCandidate).where(
                    FacultyCandidate.department_source_id == source.id,
                    FacultyCandidate.normalized_name == entry.normalized_name,
                )
            )
        if not existing:
            existing = FacultyCandidate(
                university_id=university.id,
                department_source_id=source.id,
                department_type=source.department_type,
                name=entry.name,
                normalized_name=entry.normalized_name,
                source_url=entry.source_url,
            )
            session.add(existing)
        existing.name = entry.name
        existing.normalized_name = entry.normalized_name
        existing.title = entry.title
        existing.email = entry.email
        existing.profile_url = entry.profile_url
        existing.profile_text = entry.profile_text
        existing.source_url = entry.source_url
        existing.source_snippet = entry.source_snippet
        existing.evidence_json = entry.as_evidence_json()
        existing.scrape_status = "captured"
        existing.scraped_at = datetime.now(timezone.utc)

    def run(self, session: Session, *, limit: int | None = None) -> dict[str, int]:
        query = (
            select(DepartmentSource, University)
            .join(University, University.id == DepartmentSource.university_id)
            .where(or_(DepartmentSource.status == "pending", DepartmentSource.status == "error"))
            .order_by(DepartmentSource.id)
        )
        rows = session.execute(query).all()
        if limit is not None:
            rows = rows[:limit]
        if self.reporter:
            self.reporter.stage_started(self.name, total_items=len(rows))
        self.mark_started(session, total_items=len(rows))
        processed = 0
        for source, university in rows:
            approved_domains = {university.domain}
            result = asyncio.run(self._scrape_source(source, approved_domains))
            if result.error:
                source.status = "error"
                source.error_message = result.error
            else:
                for entry in result.entries:
                    self._upsert_candidate(session, source, university, entry)
                source.status = "scraped"
                source.error_message = None
                source.last_scraped_at = datetime.now(timezone.utc)
                university.status = "faculty_scraped"
            if self.reporter:
                self.reporter.record_stage2_source(
                    {
                        "department_source_id": source.id,
                        "university": university.name,
                        "department_type": source.department_type,
                        "roster_url": source.roster_url,
                        "parser_hint": source.parser_hint,
                        "status": source.status,
                        "error": source.error_message,
                        "entries_found": len(result.entries),
                        "pages": [asdict(page) for page in result.pages],
                        "final_url": result.final_url,
                    }
                )
            processed += 1
            self.mark_progress(
                session,
                processed,
                {"last_department_source_id": source.id, "last_url": result.final_url},
            )
        self.mark_completed(session)
        return {"sources_processed": processed}
