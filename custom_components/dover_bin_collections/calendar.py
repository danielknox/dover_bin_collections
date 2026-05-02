from __future__ import annotations

import datetime as dt
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEVICE_MANUFACTURER, DOMAIN
from .coordinator import DoverBinCollectionsCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: DoverBinCollectionsCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DoverCollectionsCalendar(coordinator, entry.entry_id)])


class DoverCollectionsCalendar(CoordinatorEntity[DoverBinCollectionsCoordinator], CalendarEntity):
    _attr_has_entity_name = True
    _attr_name = "Collection Calendar"

    def __init__(self, coordinator: DoverBinCollectionsCoordinator, entry_id: str) -> None:
        super().__init__(coordinator)
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_collection_calendar"

    @property
    def event(self) -> CalendarEvent | None:
        today = dt.date.today()
        future_events = sorted(
            (
                event
                for event in self.coordinator.calendar_events
                if self._event_date(event) is not None and self._event_date(event) >= today
            ),
            key=lambda event: event["date"],
        )
        if not future_events:
            return None
        return self._to_calendar_event(future_events[0])

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: dt.datetime,
        end_date: dt.datetime,
    ) -> list[CalendarEvent]:
        start = start_date.date()
        end = end_date.date()
        events: list[CalendarEvent] = []
        for event in self.coordinator.calendar_events:
            event_date = self._event_date(event)
            if event_date is not None and start <= event_date < end:
                events.append(self._to_calendar_event(event))
        return sorted(events, key=lambda event: event.start)

    @staticmethod
    def _event_date(event: dict[str, Any]) -> dt.date | None:
        try:
            return dt.date.fromisoformat(event["date"])
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _to_calendar_event(event: dict[str, Any]) -> CalendarEvent:
        start = dt.date.fromisoformat(event["date"])
        description = event.get("description")
        if event.get("current") is False:
            description = (description + "\n" if description else "") + "No longer in current upcoming schedule."
        return CalendarEvent(
            uid=event.get("uid"),
            summary=event["summary"],
            start=start,
            end=start + dt.timedelta(days=1),
            description=description,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "event_count": len(self.coordinator.calendar_events),
            "current_event_count": sum(1 for event in self.coordinator.calendar_events if event.get("current")),
            "source_url": self.coordinator.data.get("url"),
            "fetched_at": self.coordinator.data.get("fetched_at"),
        }

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name="Dover Bin Collections",
            manufacturer=DEVICE_MANUFACTURER,
            configuration_url=self.coordinator.url,
        )
