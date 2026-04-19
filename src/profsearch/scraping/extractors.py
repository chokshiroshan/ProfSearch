"""Roster extraction helpers for common faculty page layouts."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Iterable
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from profsearch.scraping.normalize import normalize_email, normalize_name, normalize_whitespace

EMAIL_SCRIPT_NAME_RE = re.compile(r'var\s+name\s*=\s*"([^"]+)"', re.IGNORECASE)
EMAIL_SCRIPT_DOMAIN_RE = re.compile(r'var\s+domain\s*=\s*"([^"]+)"', re.IGNORECASE)


@dataclass(slots=True)
class RosterEntry:
    name: str
    title: str | None
    email: str | None
    profile_url: str | None
    profile_text: str | None
    source_url: str
    source_snippet: str

    @property
    def normalized_name(self) -> str:
        return normalize_name(self.name)

    def as_evidence_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


@dataclass(slots=True)
class ProfileDetails:
    title: str | None
    email: str | None
    profile_text: str | None
    source_url: str
    source_snippet: str


def _text(node: Tag | None) -> str:
    if node is None:
        return ""
    return normalize_whitespace(node.get_text(" ", strip=True))


def _anchor_href(node: Tag | None, base_url: str) -> str | None:
    if node is None:
        return None
    anchor = node.find("a", href=True) if node.name != "a" else node
    if not anchor:
        return None
    return urljoin(base_url, anchor["href"])


def _build_entry(
    name: str,
    title: str | None,
    email: str | None,
    profile_url: str | None,
    source_url: str,
    snippet: str,
    profile_text: str | None = None,
) -> RosterEntry | None:
    clean_name = normalize_whitespace(name)
    if not clean_name or len(clean_name.split()) < 2:
        return None
    return RosterEntry(
        name=clean_name,
        title=normalize_whitespace(title) or None,
        email=normalize_email(email),
        profile_url=profile_url,
        profile_text=normalize_whitespace(profile_text)[:4000] or None,
        source_url=source_url,
        source_snippet=normalize_whitespace(snippet)[:600],
    )


def _script_email(node: Tag | None) -> str | None:
    if node is None:
        return None
    for script in node.select("script"):
        content = script.get_text(" ", strip=True)
        name_match = EMAIL_SCRIPT_NAME_RE.search(content)
        domain_match = EMAIL_SCRIPT_DOMAIN_RE.search(content)
        if name_match and domain_match:
            return normalize_email(f"{name_match.group(1)}@{domain_match.group(1)}")
    return None


def _mit_faculty_cards(soup: BeautifulSoup, source_url: str) -> list[RosterEntry]:
    entries: list[RosterEntry] = []
    for card in soup.select(".card.faculty-card"):
        name = _text(card.select_one("h3"))
        title = _text(card.select_one(".faculty-card__job-title"))
        snippet = _text(card)
        entry = _build_entry(name, title, snippet, _anchor_href(card.select_one("h3 a"), source_url), source_url, snippet)
        if entry:
            entries.append(entry)
    return entries


def _mit_dmse_cards(soup: BeautifulSoup, source_url: str) -> list[RosterEntry]:
    entries: list[RosterEntry] = []
    for card in soup.select(".faculty-teaser"):
        name = _text(card.select_one(".faculty-teaser__name"))
        title = _text(card.select_one(".faculty-teaser__title"))
        snippet = _text(card)
        entry = _build_entry(name, title, snippet, _anchor_href(card, source_url), source_url, snippet)
        if entry:
            entries.append(entry)
    return entries


def _stanford_cards(soup: BeautifulSoup, source_url: str) -> list[RosterEntry]:
    entries: list[RosterEntry] = []
    for card in soup.select(".hb-card.hb-vertical-card"):
        name_link = card.select_one(".hb-card__title a, h2 a, h3 a")
        name = _text(name_link)
        title = _text(card.select_one(".hb-card__description, .hb-card__title + div"))
        if not title:
            lines = [_text(item) for item in card.select(".field-content")]
            title = next((line for line in lines if "professor" in line.lower()), "")
        snippet = _text(card)
        email = normalize_email(snippet)
        entry = _build_entry(name, title, email, _anchor_href(name_link, source_url), source_url, snippet)
        if entry:
            entries.append(entry)
    for card in soup.select("article.su-card.su-card--minimal"):
        name_link = card.select_one("h3 a, h2 a")
        name = _text(name_link)
        title = _text(card.select_one(".su-person-short-title, .su-card__description"))
        snippet = _text(card)
        email = normalize_email(snippet)
        entry = _build_entry(name, title, email, _anchor_href(name_link, source_url), source_url, snippet)
        if entry:
            entries.append(entry)
    for row in soup.select(".views-row"):
        name_link = row.select_one(".views-field-view-profile a, h2 a, h3 a")
        name = _text(name_link)
        title = _text(row.select_one(".field-position, .su-person-short-title"))
        snippet = _text(row)
        email = normalize_email(snippet)
        entry = _build_entry(name, title, email, _anchor_href(name_link, source_url), source_url, snippet)
        if entry:
            entries.append(entry)
    return entries


def _berkeley_table(soup: BeautifulSoup, source_url: str) -> list[RosterEntry]:
    entries: list[RosterEntry] = []
    rows = soup.select("table tr")
    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        name = _text(cells[0])
        title = _text(cells[1])
        role = _text(cells[2]) if len(cells) >= 3 else ""
        if role and "faculty" not in role.lower():
            continue
        snippet = _text(row)
        entry = _build_entry(name, title, snippet, _anchor_href(cells[0], source_url), source_url, snippet)
        if entry:
            entries.append(entry)
    for row in soup.select(".views-row"):
        name_link = row.select_one("h2 a, h3 a")
        name = _text(name_link)
        title = _text(row.select_one(".field-name-field-openberkeley-person-title .field-item"))
        snippet = _text(row)
        entry = _build_entry(name, title, snippet, _anchor_href(name_link, source_url), source_url, snippet)
        if entry:
            entries.append(entry)
    return entries


def _caltech_people_listing(soup: BeautifulSoup, source_url: str) -> list[RosterEntry]:
    entries: list[RosterEntry] = []
    for row in soup.select(".person-listing__person-row"):
        name = _text(row.select_one(".person-listing__summary__title"))
        title = _text(row.select_one(".person-listing__summary__faculty-title"))
        snippet = _text(row)
        email = normalize_email(snippet)
        entry = _build_entry(
            name,
            title,
            email,
            _anchor_href(row.select_one(".person-listing__person-row__wrapper-link"), source_url),
            source_url,
            snippet,
        )
        if entry:
            entries.append(entry)
    return entries


def _yale_people_table(soup: BeautifulSoup, source_url: str) -> list[RosterEntry]:
    entries: list[RosterEntry] = []
    for row in soup.select("table.views-table tr"):
        name_cell = row.select_one("td.views-field-name")
        if not name_cell:
            continue
        name_link = name_cell.select_one("a.username, a[href]")
        name = _text(name_link)
        lines = [normalize_whitespace(text) for text in name_cell.stripped_strings]
        title = lines[1] if len(lines) > 1 else None
        snippet = _text(row)
        email = normalize_email(snippet)
        entry = _build_entry(name, title, email, _anchor_href(name_link, source_url), source_url, snippet)
        if entry:
            entries.append(entry)
    return entries


def _ucsb_directory_rows(soup: BeautifulSoup, source_url: str) -> list[RosterEntry]:
    entries: list[RosterEntry] = []
    for row in soup.select(".views-row"):
        details = row.select_one(".group-second")
        if not details:
            continue
        name_link = details.select_one("h3 a")
        name = _text(name_link)
        lines = [normalize_whitespace(text) for text in details.stripped_strings]
        title = next((line for line in lines[1:] if "professor" in line.lower() or "lecturer" in line.lower()), None)
        snippet = _text(row)
        email = normalize_email(snippet)
        profile_text = _text(row.select_one(".group-third"))
        entry = _build_entry(
            name,
            title,
            email,
            _anchor_href(name_link, source_url),
            source_url,
            snippet,
            profile_text=profile_text,
        )
        if entry:
            entries.append(entry)
    return entries


def _uchicago_people_list(soup: BeautifulSoup, source_url: str) -> list[RosterEntry]:
    entries: list[RosterEntry] = []
    for row in soup.select("li.mix.faculty"):
        name_link = row.select_one("a[href]")
        name = _text(row.select_one(".people_img h5")) or _text(row.select_one(".people_content h3 span"))
        title = _text(row.select_one(".people_content h3 b"))
        snippet = _text(row)
        entry = _build_entry(name, title, normalize_email(snippet), _anchor_href(name_link, source_url), source_url, snippet)
        if entry:
            entries.append(entry)
    return entries


def _princeton_content_list(soup: BeautifulSoup, source_url: str) -> list[RosterEntry]:
    entries: list[RosterEntry] = []
    for card in soup.select(".content-list-item"):
        name_link = card.select_one(".field--name-title a")
        name = _text(name_link or card.select_one(".field--name-title"))
        title = _text(card.select_one(".field--name-field-ps-people-position .field__item"))
        if not title:
            title = _text(card.select_one(".field--name-field-ps-people-position"))
        snippet = _text(card)
        entry = _build_entry(name, title, normalize_email(snippet), _anchor_href(name_link, source_url), source_url, snippet)
        if entry:
            entries.append(entry)
    return entries


def _penn_people_rows(soup: BeautifulSoup, source_url: str) -> list[RosterEntry]:
    entries: list[RosterEntry] = []
    for row in soup.select(".views-row"):
        name_link = row.select_one("h3 a[href]")
        name = _text(name_link)
        title = _text(row.select_one("p.title .title"))
        email = _text(row.select_one(".email a"))
        snippet = _text(row)
        entry = _build_entry(name, title, email, _anchor_href(name_link, source_url), source_url, snippet)
        if entry:
            entries.append(entry)
    return entries


def _ucla_faculty_table(soup: BeautifulSoup, source_url: str) -> list[RosterEntry]:
    entries: list[RosterEntry] = []
    for row in soup.select("tr"):
        cell = row.find("td")
        if not cell:
            continue
        name = _text(cell.select_one("h5"))
        if not name:
            continue
        paragraph = cell.select_one("p")
        lines = [normalize_whitespace(text) for text in paragraph.stripped_strings] if paragraph else []
        title = lines[0] if lines else None
        email = _script_email(cell) or normalize_email(_text(cell))
        website_link = next(
            (
                anchor
                for anchor in cell.select("a[href]")
                if not (anchor.get("href") or "").lower().startswith("mailto:")
            ),
            None,
        )
        snippet = _text(cell)
        entry = _build_entry(name, title, email, _anchor_href(website_link, source_url), source_url, snippet)
        if entry:
            entries.append(entry)
    return entries


def _umd_k2_faculty(soup: BeautifulSoup, source_url: str) -> list[RosterEntry]:
    entries: list[RosterEntry] = []
    for card in soup.select(".catItemView.groupPrimary"):
        name_link = card.select_one(".catItemTitle a[href]")
        name = _text(name_link or card.select_one(".catItemTitle"))
        if not name:
            continue
        fields: dict[str, str] = {}
        for label_node in card.select(".catItemExtraFieldsLabel"):
            label = _text(label_node).rstrip(":").lower()
            value_node = label_node.find_next_sibling("span", class_="catItemExtraFieldsValue")
            value = _text(value_node)
            if label and value:
                fields[label] = value
        title = fields.get("title")
        email = fields.get("e-mail") or fields.get("email")
        snippet = _text(card)
        entry = _build_entry(name, title, email, _anchor_href(name_link, source_url), source_url, snippet)
        if entry:
            entries.append(entry)
    return entries


def _washington_views_rows(soup: BeautifulSoup, source_url: str) -> list[RosterEntry]:
    entries: list[RosterEntry] = []
    for row in soup.select(".thin-top-border-gray.views-row"):
        name_link = row.select_one(".views-field-title a[href], h3.field-content a[href]")
        name = _text(name_link)
        title = _text(row.select_one(".views-field-field-job-title .field-content"))
        email = _text(row.select_one(".views-field-field-email a[href^='mailto:']"))
        profile_text = _text(row.select_one(".views-field-term-node-tid"))
        snippet = _text(row)
        entry = _build_entry(
            name,
            title,
            email,
            _anchor_href(name_link, source_url),
            source_url,
            snippet,
            profile_text=profile_text,
        )
        if entry:
            entries.append(entry)
    return entries


def _gatech_people_grid(soup: BeautifulSoup, source_url: str) -> list[RosterEntry]:
    entries: list[RosterEntry] = []
    for row in soup.select(".people ul.grid > li, .people .grid > li"):
        name_link = row.select_one(".p-name a[href], h3 a[href]")
        name = _text(name_link)
        snippet = _text(row)
        entry = _build_entry(name, None, None, _anchor_href(name_link, source_url), source_url, snippet)
        if entry:
            entries.append(entry)
    return entries


def _northwestern_people_articles(soup: BeautifulSoup, source_url: str) -> list[RosterEntry]:
    entries: list[RosterEntry] = []
    for card in soup.select("article.people"):
        name_link = card.select_one("h3 a[href]")
        name = re.sub(r"\s*\([^)]*\)\s*$", "", _text(name_link))
        title = _text(card.select_one("p.title"))
        email = _text(card.select_one("a[href^='mailto:']"))
        snippet = _text(card)
        entry = _build_entry(name, title, email, _anchor_href(name_link, source_url), source_url, snippet)
        if entry:
            entries.append(entry)
    return entries


def _wisc_faculty_cards(soup: BeautifulSoup, source_url: str) -> list[RosterEntry]:
    entries: list[RosterEntry] = []
    for card in soup.select(".faculty-member"):
        name_link = card.select_one("a.faculty-name[href]")
        name = _text(name_link)
        title = _text(card.select_one(".position-title"))
        title = re.sub(r"^Position title:\s*", "", title, flags=re.IGNORECASE)
        snippet = _text(card)
        entry = _build_entry(name, title, normalize_email(snippet), _anchor_href(name_link, source_url), source_url, snippet)
        if entry:
            entries.append(entry)
    return entries


def _generic_cards(soup: BeautifulSoup, source_url: str) -> list[RosterEntry]:
    entries: list[RosterEntry] = []
    candidate_selectors = [
        ".person",
        ".faculty-card",
        ".faculty-teaser",
        ".hb-card",
        "article",
        ".views-row",
        "li",
    ]
    seen: set[tuple[str, str | None]] = set()
    for selector in candidate_selectors:
        for node in soup.select(selector):
            text = _text(node)
            if "professor" not in text.lower():
                continue
            anchor = node.find("a", href=True)
            if not anchor:
                continue
            name = _text(anchor)
            if len(name.split()) < 2:
                continue
            lines = [normalize_whitespace(line) for line in node.stripped_strings]
            title = next((line for line in lines if "professor" in line.lower() and line != name), None)
            entry = _build_entry(name, title, text, _anchor_href(anchor, source_url), source_url, text)
            if entry and (entry.normalized_name, entry.profile_url) not in seen:
                seen.add((entry.normalized_name, entry.profile_url))
                entries.append(entry)
        if entries:
            return entries
    return entries


def _is_noise_chunk(text: str) -> bool:
    lowered = text.lower()
    return any(
        pattern in lowered
        for pattern in [
            "home people faculty",
            "contact info",
            "office phone",
            "assistant email",
            "assistant name",
            "assistant phone",
            "website/lab",
            "affiliated center",
            "primary impact",
            "research type",
        ]
    )


def _candidate_profile_chunks(soup: BeautifulSoup) -> list[str]:
    selectors = [
        ".su-person-long-bio",
        ".su-person-short-bio",
        ".su-person-research-interests",
        ".field-name-field-research",
        ".field-name-body",
        ".field--name-body",
        ".person-bio",
        ".profile-bio",
        ".research",
        ".biography",
    ]
    chunks: list[str] = []
    seen: set[str] = set()
    for selector in selectors:
        for node in soup.select(selector):
            text = _text(node)
            if len(text.split()) < 8 or text in seen or _is_noise_chunk(text):
                continue
            seen.add(text)
            chunks.append(text)
        if chunks:
            break
    if chunks:
        return chunks
    fallback_root = soup.select_one("main") or soup.select_one("article") or soup.body
    if not fallback_root:
        return []
    for node in fallback_root.select("p, li"):
        text = _text(node)
        if len(text.split()) < 8 or text in seen or _is_noise_chunk(text):
            continue
        seen.add(text)
        chunks.append(text)
    return chunks


def _extract_profile_text(soup: BeautifulSoup) -> str | None:
    chunks = _candidate_profile_chunks(soup)
    if not chunks:
        return None
    return normalize_whitespace(" ".join(chunks))[:4000] or None


PARSER_HINTS = {
    "mit_faculty_cards": _mit_faculty_cards,
    "mit_dmse_cards": _mit_dmse_cards,
    "stanford_hb_cards": _stanford_cards,
    "berkeley_people_table": _berkeley_table,
    "caltech_people_listing": _caltech_people_listing,
    "princeton_content_list": _princeton_content_list,
    "penn_people_rows": _penn_people_rows,
    "ucla_faculty_table": _ucla_faculty_table,
    "umd_k2_faculty": _umd_k2_faculty,
    "washington_views_rows": _washington_views_rows,
    "gatech_people_grid": _gatech_people_grid,
    "northwestern_people_articles": _northwestern_people_articles,
    "wisc_faculty_cards": _wisc_faculty_cards,
    "uchicago_people_list": _uchicago_people_list,
    "yale_people_table": _yale_people_table,
    "ucsb_directory_rows": _ucsb_directory_rows,
}


def dedupe_entries(entries: Iterable[RosterEntry]) -> list[RosterEntry]:
    deduped: list[RosterEntry] = []
    seen: set[tuple[str, str | None, str]] = set()
    for entry in entries:
        key = (entry.normalized_name, entry.profile_url, entry.source_url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


def extract_roster_entries(html: str, source_url: str, parser_hint: str | None = None) -> list[RosterEntry]:
    soup = BeautifulSoup(html, "html.parser")
    if parser_hint and parser_hint in PARSER_HINTS:
        parsed = PARSER_HINTS[parser_hint](soup, source_url)
        return dedupe_entries(parsed)
    parsed = _generic_cards(soup, source_url)
    return dedupe_entries(parsed)


def extract_profile_details(html: str, profile_url: str) -> ProfileDetails:
    soup = BeautifulSoup(html, "html.parser")
    title_selectors = [
        ".field-position",
        ".su-person-short-title",
        ".field-name-field-openberkeley-person-title .field-item",
        ".faculty-card__job-title",
        ".faculty-teaser__title",
        ".field--name-field-title",
        ".person-title",
        ".gtppl-header-txt p",
    ]
    title = ""
    for selector in title_selectors:
        title = _text(soup.select_one(selector))
        if title:
            break
    if not title:
        for line in soup.stripped_strings:
            cleaned = normalize_whitespace(line)
            if "professor" in cleaned.lower():
                title = cleaned
                break
    full_text = _text(soup)
    email = normalize_email(full_text)
    profile_text = _extract_profile_text(soup)
    snippet = title or profile_text or full_text[:600]
    return ProfileDetails(
        title=title or None,
        email=email,
        profile_text=profile_text,
        source_url=profile_url,
        source_snippet=snippet,
    )


def extract_pagination_urls(html: str, source_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    source_parts = urlparse(source_url)
    urls: list[str] = []
    seen: set[str] = set()
    for anchor in soup.select("a[href]"):
        href = urljoin(source_url, anchor["href"].split("#", 1)[0])
        parts = urlparse(href)
        if parts.netloc != source_parts.netloc or parts.path != source_parts.path:
            continue
        query = parse_qs(parts.query)
        if "page" not in query:
            continue
        if href not in seen and href != source_url:
            seen.add(href)
            urls.append(href)
    return urls
