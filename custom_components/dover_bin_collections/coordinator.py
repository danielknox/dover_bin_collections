from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    ATTR_CURRENT,
    ATTR_FIRST_SEEN_AT,
    ATTR_LAST_SEEN_AT,
    ATTR_SOURCE,
    DEFAULT_EVENT_RETENTION_DAYS,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
)
from .parser import (
    DoverCollectionsConnectionError,
    DoverCollectionsParseError,
    build_url,
    fetch_page,
    parse_services,
    payload_from_services,
)

_LOGGER = logging.getLogger(__name__)


class DoverBinCollectionsCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(
        self,
        hass: HomeAssistant,
        *,
        entry_id: str,
        property_id: str,
        base_url: str,
        scan_interval_hours: int = DEFAULT_SCAN_INTERVAL_HOURS,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=dt.timedelta(hours=scan_interval_hours),
        )
        self.property_id = property_id
        self.base_url = base_url
        self.url = build_url(property_id, base_url)
        self._store: Store[dict[str, Any]] = Store(
            hass,
            STORAGE_VERSION,
            f"{STORAGE_KEY_PREFIX}_{entry_id}",
        )
        self._calendar_events: dict[str, dict[str, Any]] = {}
        self._store_loaded = False
        self._retention_days = DEFAULT_EVENT_RETENTION_DAYS

    @property
    def calendar_events(self) -> list[dict[str, Any]]:
        return [self._calendar_events[key] for key in sorted(self._calendar_events)]

    async def _async_load_store(self) -> None:
        if self._store_loaded:
            return
        stored = await self._store.async_load()
        if stored and isinstance(stored.get("events"), dict):
            self._calendar_events = stored["events"]
            self._migrate_stored_events()
        self._prune_old_events()
        self._mark_all_events_not_current()
        self._store_loaded = True

    async def _async_save_store(self) -> None:
        await self._store.async_save({"events": self._calendar_events})

    async def _async_update_data(self) -> dict[str, Any]:
        await self._async_load_store()
        try:
            html_text = await self.hass.async_add_executor_job(fetch_page, self.url)
            services = await self.hass.async_add_executor_job(parse_services, html_text)
            payload = payload_from_services(self.url, services)
        except DoverCollectionsConnectionError as exc:
            raise UpdateFailed(str(exc)) from exc
        except DoverCollectionsParseError as exc:
            raise UpdateFailed(f"Collections page format changed or was incomplete: {exc}") from exc
        except Exception as exc:
            raise UpdateFailed(f"Unexpected Dover collections error: {exc}") from exc

        changed = self._merge_calendar_events(payload)
        if changed:
            await self._async_save_store()

        payload["calendar_events"] = self.calendar_events
        return payload

    def _merge_calendar_events(self, payload: dict[str, Any]) -> bool:
        changed = False
        fetched_at = payload["fetched_at"]
        current_keys: set[str] = set()
        current_single_service_dates: set[str] = set()

        for event in payload["next_collections"]:
            key = self._event_key(event["date"], event["services"])
            current_keys.add(key)
            if len(event["services"]) == 1:
                current_single_service_dates.add(event["date"])
            new_value = {
                "uid": key,
                "date": event["date"],
                "summary": event["summary"],
                "services": event["services"],
                "description": "Service: " + event["services"][0]
                if len(event["services"]) == 1
                else "Services: " + ", ".join(event["services"]),
                ATTR_CURRENT: True,
                ATTR_SOURCE: payload.get("source"),
                ATTR_LAST_SEEN_AT: fetched_at,
            }
            existing = self._calendar_events.get(key)
            if existing is None:
                new_value[ATTR_FIRST_SEEN_AT] = fetched_at
                self._calendar_events[key] = new_value
                changed = True
                continue

            first_seen = existing.get(ATTR_FIRST_SEEN_AT, fetched_at)
            merged = {**existing, **new_value, ATTR_FIRST_SEEN_AT: first_seen}
            if merged != existing:
                self._calendar_events[key] = merged
                changed = True

        for key, event in list(self._calendar_events.items()):
            if self._is_superseded_combined_event(event, current_single_service_dates):
                self._calendar_events.pop(key, None)
                changed = True
                continue
            should_be_current = key in current_keys
            if event.get(ATTR_CURRENT) != should_be_current:
                event[ATTR_CURRENT] = should_be_current
                changed = True

        if self._prune_old_events():
            changed = True

        return changed

    def _migrate_stored_events(self) -> None:
        for key in list(self._calendar_events):
            event = self._calendar_events.get(key)
            if not isinstance(event, dict) or "date" not in event:
                self._calendar_events.pop(key, None)
                continue
            event.setdefault(ATTR_CURRENT, False)
            if ATTR_FIRST_SEEN_AT not in event and ATTR_LAST_SEEN_AT in event:
                event[ATTR_FIRST_SEEN_AT] = event[ATTR_LAST_SEEN_AT]

    def _mark_all_events_not_current(self) -> None:
        for event in self._calendar_events.values():
            event[ATTR_CURRENT] = False

    @staticmethod
    def _is_superseded_combined_event(event: dict[str, Any], current_single_service_dates: set[str]) -> bool:
        """Return True for old grouped events replaced by per-service events."""
        services = event.get("services")
        return (
            isinstance(services, list)
            and len(services) > 1
            and event.get("date") in current_single_service_dates
        )

    def _prune_old_events(self) -> bool:
        if not self._calendar_events:
            return False
        cutoff = dt.date.today() - dt.timedelta(days=self._retention_days)
        to_remove: list[str] = []
        for key, event in self._calendar_events.items():
            try:
                event_date = dt.date.fromisoformat(event["date"])
            except (KeyError, TypeError, ValueError):
                to_remove.append(key)
                continue
            if event_date < cutoff:
                to_remove.append(key)
        for key in to_remove:
            self._calendar_events.pop(key, None)
        return bool(to_remove)

    @staticmethod
    def _event_key(date: str, services: list[str]) -> str:
        service_part = "_".join(sorted(s.lower().replace("/", "_").replace(" ", "_") for s in services))
        return f"{date}_{service_part}"
