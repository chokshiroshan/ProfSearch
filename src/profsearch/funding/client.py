"""Clients for NIH RePORTER and NSF Awards APIs.

Both are public, unauthenticated endpoints that return active grants
searchable by PI name and institution. Used by stage7_funding to
enrich professors with a "funded" signal.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

import httpx

from profsearch.config import FundingConfig

logger = logging.getLogger(__name__)


@dataclass
class RawGrant:
    """Normalised grant record from either source."""

    source: str  # "nih" or "nsf"
    grant_id: str
    title: str
    pi_name: str
    amount: float | None
    start_date: str | None  # ISO date string
    end_date: str | None
    raw_json: str


# ── NIH RePORTER ──


def _parse_nih_grant(item: dict) -> RawGrant:
    """Parse a single project from NIH RePORTER v2 response."""
    award = item.get("award_amount") or item.get("award_amount_per_year")
    start = item.get("project_start_date")
    end = item.get("project_end_date")

    pi_list = item.get("principal_investigators") or []
    pi_name = pi_list[0].get("full_name", "") if pi_list else ""

    return RawGrant(
        source="nih",
        grant_id=str(item.get("applied_serial_num", item.get("project_num", ""))),
        title=item.get("project_title", ""),
        pi_name=pi_name,
        amount=float(award) if award is not None else None,
        start_date=str(start)[:10] if start else None,
        end_date=str(end)[:10] if end else None,
        raw_json="",
    )


def fetch_nih_grants(
    *,
    pi_name: str,
    institution: str,
    config: FundingConfig,
    http_timeout: float = 20.0,
) -> list[RawGrant]:
    """Search NIH RePORTER for active grants by PI name + institution."""
    grants: list[RawGrant] = []
    url = f"{config.nih_base_url.rstrip('/')}/projects/search"

    for page in range(config.max_pages):
        payload = {
            "criteria": {
                "pi_names": [{"full_name": pi_name}],
                "org_names": [{"name": institution}],
                "active_projects": True,
            },
            "offset": page * config.per_page,
            "limit": config.per_page,
            "sort_field": "project_start_date",
            "sort_order": "desc",
        }
        try:
            resp = httpx.post(url, json=payload, timeout=http_timeout)
            if resp.status_code != 200:
                logger.warning("NIH RePORTER returned HTTP %d for %s", resp.status_code, pi_name)
                break
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("NIH RePORTER request failed for %s: %s", pi_name, exc)
            break

        items = data.get("results") or []
        for item in items:
            grant = _parse_nih_grant(item)
            grant.raw_json = json.dumps(item, default=str)
            grants.append(grant)

        if len(items) < config.per_page:
            break
        time.sleep(0.3)

    return grants


# ── NSF Awards ──


def _parse_nsf_grant(item: dict) -> RawGrant:
    """Parse a single award from NSF Awards API response."""
    funds = item.get("fundsObligatedAmt") or item.get("funds")
    start = item.get("startDate", {}).get("date") if isinstance(item.get("startDate"), dict) else item.get("startDate")
    end = item.get("expDate", {}).get("date") if isinstance(item.get("expDate"), dict) else item.get("expDate")
    pi = item.get("piFirstName", "") + " " + item.get("piLastName", "")

    return RawGrant(
        source="nsf",
        grant_id=str(item.get("id", "")),
        title=item.get("title", ""),
        pi_name=pi.strip(),
        amount=float(funds) if funds is not None else None,
        start_date=str(start)[:10] if start else None,
        end_date=str(end)[:10] if end else None,
        raw_json="",
    )


def fetch_nsf_grants(
    *,
    pi_last_name: str,
    institution: str,
    config: FundingConfig,
    http_timeout: float = 20.0,
) -> list[RawGrant]:
    """Search NSF Awards API for active grants by PI last name + institution."""
    grants: list[RawGrant] = []
    url = f"{config.nsf_base_url.rstrip('/')}/awards.json"

    for page in range(config.max_pages):
        params = {
            "piLastName": pi_last_name,
            "piFirstName": "",
            "institution": institution,
            "offset": page * config.per_page,
            "limit": config.per_page,
        }
        try:
            resp = httpx.get(url, params=params, timeout=http_timeout)
            if resp.status_code != 200:
                logger.warning("NSF Awards API returned HTTP %d for %s", resp.status_code, pi_last_name)
                break
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("NSF Awards API request failed for %s: %s", pi_last_name, exc)
            break

        items = data.get("response", {}).get("award") or []
        for item in items:
            grant = _parse_nsf_grant(item)
            grant.raw_json = json.dumps(item, default=str)
            grants.append(grant)

        if len(items) < config.per_page:
            break
        time.sleep(0.3)

    return grants


# ── Combined ──


def fetch_grants(
    *,
    pi_name: str,
    institution: str,
    config: FundingConfig,
    http_timeout: float = 20.0,
) -> list[RawGrant]:
    """Fetch grants from both NIH and NSF for a given PI name + institution."""
    grants = fetch_nih_grants(
        pi_name=pi_name,
        institution=institution,
        config=config,
        http_timeout=http_timeout,
    )

    parts = pi_name.strip().split()
    last_name = parts[-1] if parts else pi_name
    nsf_grants = fetch_nsf_grants(
        pi_last_name=last_name,
        institution=institution,
        config=config,
        http_timeout=http_timeout,
    )

    grants.extend(nsf_grants)
    return grants
