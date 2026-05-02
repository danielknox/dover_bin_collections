from __future__ import annotations

import datetime as dt
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEVICE_MANUFACTURER, DOMAIN
from .coordinator import DoverBinCollectionsCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: DoverBinCollectionsCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_slugs: set[str] = set()

    def add_new_entities() -> None:
        entities: list[DoverCollectionSensor] = []
        for service in coordinator.data.get("services", []):
            slug = service["slug"]
            if slug not in known_slugs:
                known_slugs.add(slug)
                entities.append(DoverCollectionSensor(coordinator, entry.entry_id, slug))
        if entities:
            async_add_entities(entities)

    add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(add_new_entities))


class DoverCollectionSensor(CoordinatorEntity[DoverBinCollectionsCoordinator], SensorEntity):
    _attr_device_class = SensorDeviceClass.DATE
    _attr_has_entity_name = True

    def __init__(self, coordinator: DoverBinCollectionsCoordinator, entry_id: str, slug: str) -> None:
        super().__init__(coordinator)
        self._slug = slug
        self._entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_{slug}_next_collection"

    @property
    def _service(self) -> dict[str, Any] | None:
        for service in self.coordinator.data.get("services", []):
            if service.get("slug") == self._slug:
                return service
        return None

    @property
    def available(self) -> bool:
        return super().available and self._service is not None

    @property
    def name(self) -> str | None:
        service = self._service
        if service:
            return f"{service['name']} Next Collection"
        return f"{self._slug.replace('_', ' ').title()} Next Collection"

    @property
    def native_value(self) -> dt.date | None:
        service = self._service
        if not service or not service.get("next_collection_date"):
            return None
        try:
            return dt.date.fromisoformat(service["next_collection_date"])
        except (TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        service = self._service or {}
        return {
            "service_name": service.get("name"),
            "service_slug": self._slug,
            "collection_day": service.get("collection_day"),
            "last_collection_date": service.get("last_collection_date"),
            "last_collection_status": service.get("last_collection_status"),
            "last_collection_completed": service.get("last_collection_completed"),
            "last_collection_completed_at": service.get("last_collection_completed_at"),
            "raw_last_collection_status": service.get("raw_last_collection_status"),
            "service_id": service.get("service_id"),
            "task_id": service.get("task_id"),
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
