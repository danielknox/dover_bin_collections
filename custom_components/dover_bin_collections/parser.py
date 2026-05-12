from __future__ import annotations

import datetime as dt
import html
import json
import re
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any
from zoneinfo import ZoneInfo

from .const import DEFAULT_BASE_URL, DEFAULT_TIME_ZONE, SOURCE_NAME

def clean_property_id(property_id: str) -> str:
    """Return a safe Dover portal point ID for URL and API use."""
    return str(property_id).strip()


def resolve_point_id(property_id: str) -> str:
    """Return the Dover portal pointId used by the current collections API."""
    return clean_property_id(property_id)


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
    property_id = clean_property_id(property_id)
    point_id = resolve_point_id(property_id)
    base = base_url.rstrip("/")
    if "portal.waste.dover.gov.uk" in base:
        return f"{base}/recycling-rubbish/property-search/{point_id}/your-collection-days"
    return f"{base}/property/{property_id}"


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



def parse_iso_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        return None


def parse_iso_datetime(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value).isoformat()
    except ValueError:
        return None


def collection_day_from_schedule(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b", value, flags=re.I)
    return match.group(1).title() if match else value


def parse_api_status(schedule: dict[str, Any] | None) -> tuple[str | None, bool | None, str | None]:
    if not schedule:
        return None, None, None
    state = schedule.get("state")
    core_state = schedule.get("coreStateName")
    status = None
    if isinstance(state, str):
        match = re.search(r"Last collection:\s*(.+)", state, flags=re.I)
        status = match.group(1).strip() if match else state.strip()
    elif isinstance(core_state, str):
        status = core_state.strip()
    completed = None
    if status:
        completed = status.lower() in {"complete", "completed", "closed"}
    if isinstance(core_state, str) and core_state.lower() in {"complete", "closed"}:
        completed = True
    return status, completed, parse_iso_datetime(schedule.get("completedDate"))


def parse_api_services(api_payload: dict[str, Any], tz_name: str = DEFAULT_TIME_ZONE) -> list[CollectionService]:
    services: list[CollectionService] = []
    for item in api_payload.get("activeServices") or []:
        if not isinstance(item, dict):
            continue
        name = item.get("taskTypeName") or item.get("serviceName")
        if not isinstance(name, str) or not name.strip():
            continue
        schedules = [s for s in (item.get("serviceSchedules") or []) if isinstance(s, dict)]
        last_schedule = schedules[0] if schedules else None
        next_schedule = schedules[1] if len(schedules) > 1 else None
        if next_schedule is None and schedules:
            today = dt.datetime.now(tz=ZoneInfo(tz_name)).date()
            for schedule in schedules:
                schedule_date = parse_iso_date(schedule.get("currentScheduledDate"))
                if schedule_date and dt.date.fromisoformat(schedule_date) >= today:
                    next_schedule = schedule
                    break
        status, completed, completed_at = parse_api_status(last_schedule)
        raw_status = last_schedule.get("state") if isinstance(last_schedule, dict) else None
        services.append(
            CollectionService(
                name=name.strip(),
                slug=slugify(name),
                service_id=str(item.get("serviceId")) if item.get("serviceId") is not None else None,
                task_id=str(item.get("taskTypeId")) if item.get("taskTypeId") is not None else None,
                collection_day=collection_day_from_schedule(item.get("scheduleDescription")),
                last_collection_date=parse_iso_date(last_schedule.get("currentScheduledDate")) if last_schedule else None,
                next_collection_date=parse_iso_date(next_schedule.get("currentScheduledDate")) if next_schedule else None,
                last_collection_status=status,
                last_collection_completed=completed,
                last_collection_completed_at=completed_at,
                raw_last_collection_status=raw_status if isinstance(raw_status, str) else None,
            )
        )
    return services

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
    try:
        api_payload = json.loads(html_text)
    except json.JSONDecodeError:
        api_payload = None
    if isinstance(api_payload, dict) and "activeServices" in api_payload:
        services = parse_api_services(api_payload, tz_name)
        if not services:
            raise DoverCollectionsParseError("No collection services found in API response")
        return services

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


def extract_property_id(url: str) -> str | None:
    match = re.search(r"/(?:property|property-search)/(\d+)(?:/|$)", url)
    return match.group(1) if match else None


def fetch_api_payload(property_id: str) -> str:
    point_id = resolve_point_id(property_id)
    api_base = "https://portal.waste.dover.gov.uk"
    referer = f"{api_base}/recycling-rubbish/property-search/{point_id}/your-collection-days"
    body = json.dumps({"pointId": point_id, "pointType": "PointAddress", "councilId": "39"}).encode()
    request = urllib.request.Request(
        f"{api_base}/api/getCollectionDays",
        data=body,
        method="POST",
        headers={
            "User-Agent": "Home Assistant Dover Bin Collections/0.3 (+https://portal.waste.dover.gov.uk/)",
            "Accept": "*/*",
            "Content-Type": "application/json",
            "Origin": api_base,
            "Referer": referer,
            "x-recaptcha-token": "",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, "replace")


def fetch_page(url: str) -> str:
    property_id = extract_property_id(url)
    if property_id:
        try:
            return fetch_api_payload(property_id)
        except urllib.error.HTTPError as exc:
            raise DoverCollectionsConnectionError(f"HTTP {exc.code} while fetching collections API") from exc
        except urllib.error.URLError as exc:
            raise DoverCollectionsConnectionError(f"Could not reach collections API: {exc.reason}") from exc
        except TimeoutError as exc:
            raise DoverCollectionsConnectionError("Timed out while fetching collections API") from exc

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Home Assistant Dover Bin Collections/0.3 (+https://portal.waste.dover.gov.uk/)",
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


def collection_events(services: list[CollectionService]) -> list[dict[str, Any]]:
    """Return one calendar event per waste service collection.

    Dover can collect several waste streams on the same day, but keeping each
    stream as its own event means more frequent services such as food waste can
    move independently without replacing a combined multi-service calendar item.
    """
    events: list[dict[str, Any]] = []
    for service in services:
        if not service.next_collection_date:
            continue
        events.append(
            {
                "date": service.next_collection_date,
                "summary": f"Bin collection: {service.name}",
                "services": [service.name],
            }
        )
    return sorted(events, key=lambda event: (event["date"], event["services"][0].lower()))


def payload_from_services(url: str, services: list[CollectionService]) -> dict[str, Any]:
    return {
        "source": SOURCE_NAME,
        "url": url,
        "fetched_at": dt.datetime.now(tz=ZoneInfo(DEFAULT_TIME_ZONE)).isoformat(),
        "services": [asdict(service) for service in services],
        "next_collections": collection_events(services),
    }
