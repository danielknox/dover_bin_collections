from __future__ import annotations

import datetime as dt
import html
import re
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any
from zoneinfo import ZoneInfo

from .const import DEFAULT_BASE_URL, DEFAULT_TIME_ZONE, SOURCE_NAME


class DoverCollectionsError(Exception):
    """Base parser/fetch error for the Dover bin collections integration."""


class DoverCollectionsConnectionError(DoverCollectionsError):
    """Network or transport error while talking to the collections portal."""


class DoverCollectionsParseError(DoverCollectionsError):
    """The page loaded, but the expected collection structure was not found."""


@dataclass
class CollectionService:
    name: str
    slug: str
    service_id: str | None
    task_id: str | None
    collection_day: str | None
    last_collection_date: str | None
    next_collection_date: str | None
    last_collection_status: str | None
    last_collection_completed: bool | None
    last_collection_completed_at: str | None
    raw_last_collection_status: str | None


def build_url(property_id: str, base_url: str = DEFAULT_BASE_URL) -> str:
    return f"{base_url.rstrip('/')}/property/{property_id}"


def slugify(value: str) -> str:
    value = value.lower().replace("/", "_").replace("&", "and")
    value = re.sub(r"\bcollection\b", "", value)
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")


def strip_tags(fragment: str) -> str:
    fragment = re.sub(r"<script\b.*?</script>", " ", fragment, flags=re.I | re.S)
    fragment = re.sub(r"<style\b.*?</style>", " ", fragment, flags=re.I | re.S)
    fragment = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_uk_date(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if not re.fullmatch(r"\d{2}/\d{2}/\d{4}", value):
        return None
    return dt.datetime.strptime(value, "%d/%m/%Y").date().isoformat()


def parse_completed_at(text: str | None, tz_name: str = DEFAULT_TIME_ZONE) -> tuple[str | None, bool | None, str | None]:
    if not text:
        return None, None, None

    match = re.search(
        r"Last collection:\s*([A-Za-z ]+?)\s*\((\d{2}/\d{2}/\d{4})\s+at\s+(\d{2}:\d{2})\)",
        text,
        flags=re.I,
    )
    if match:
        status = match.group(1).strip()
        completed_date = dt.datetime.strptime(
            f"{match.group(2)} {match.group(3)}", "%d/%m/%Y %H:%M"
        ).replace(tzinfo=ZoneInfo(tz_name))
        return status, status.lower() == "completed", completed_date.isoformat()

    match = re.search(r"Last collection:\s*([^.(]+)", text, flags=re.I)
    if match:
        status = match.group(1).strip()
        return status, status.lower() == "completed", None

    return None, None, None


def extract_td(block: str, class_name: str) -> str | None:
    match = re.search(
        rf'<td\b[^>]*class="[^"]*\b{re.escape(class_name)}\b[^"]*"[^>]*>(.*?)</td>',
        block,
        flags=re.I | re.S,
    )
    if not match:
        return None
    cell = re.sub(
        r'<span\b[^>]*class="[^"]*\btable-label\b[^"]*"[^>]*>.*?</span>',
        " ",
        match.group(1),
        flags=re.I | re.S,
    )
    return strip_tags(cell) or None


def parse_services(html_text: str, tz_name: str = DEFAULT_TIME_ZONE) -> list[CollectionService]:
    starts = [m.start() for m in re.finditer(r'<div\b[^>]*class="[^"]*\bservice-wrapper\b[^"]*"', html_text, flags=re.I)]
    blocks = [html_text[start : (starts[i + 1] if i + 1 < len(starts) else len(html_text))] for i, start in enumerate(starts)]

    services: list[CollectionService] = []
    for block in blocks:
        name_match = re.search(r'<h3\b[^>]*class="[^"]*\bservice-name\b[^"]*"[^>]*>(.*?)</h3>', block, flags=re.I | re.S)
        if not name_match:
            continue
        name = strip_tags(name_match.group(1))
        if not name:
            continue

        service_id = re.search(r"\bservice-id-(\d+)\b", block)
        task_id = re.search(r"\btask-id-(\d+)\b", block)
        status_block = re.search(r'<div\b[^>]*class="[^"]*\btask-state\b[^"]*"[^>]*>(.*?)</div>', block, flags=re.I | re.S)
        raw_status = strip_tags(status_block.group(1)) if status_block else None
        status, completed, completed_at = parse_completed_at(raw_status, tz_name)

        services.append(
            CollectionService(
                name=name,
                slug=slugify(name),
                service_id=service_id.group(1) if service_id else None,
                task_id=task_id.group(1) if task_id else None,
                collection_day=extract_td(block, "schedule"),
                last_collection_date=parse_uk_date(extract_td(block, "last-service")),
                next_collection_date=parse_uk_date(extract_td(block, "next-service")),
                last_collection_status=status,
                last_collection_completed=completed,
                last_collection_completed_at=completed_at,
                raw_last_collection_status=raw_status,
            )
        )
    if not services:
        raise DoverCollectionsParseError("No collection services found in page HTML")

    return services


def fetch_page(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Home Assistant Dover Bin Collections/0.2 (+https://collections.dover.gov.uk/)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, "replace")
    except urllib.error.HTTPError as exc:
        raise DoverCollectionsConnectionError(f"HTTP {exc.code} while fetching collections page") from exc
    except urllib.error.URLError as exc:
        raise DoverCollectionsConnectionError(f"Could not reach collections page: {exc.reason}") from exc
    except TimeoutError as exc:
        raise DoverCollectionsConnectionError("Timed out while fetching collections page") from exc


def group_events(services: list[CollectionService]) -> list[dict[str, Any]]:
    by_date: dict[str, list[str]] = {}
    for service in services:
        if service.next_collection_date:
            by_date.setdefault(service.next_collection_date, []).append(service.name)
    return [
        {
            "date": collection_date,
            "summary": "Bin collection: " + ", ".join(sorted(names)),
            "services": sorted(names),
        }
        for collection_date, names in sorted(by_date.items())
    ]


def payload_from_services(url: str, services: list[CollectionService]) -> dict[str, Any]:
    return {
        "source": SOURCE_NAME,
        "url": url,
        "fetched_at": dt.datetime.now(tz=ZoneInfo(DEFAULT_TIME_ZONE)).isoformat(),
        "services": [asdict(service) for service in services],
        "next_collections": group_events(services),
    }
