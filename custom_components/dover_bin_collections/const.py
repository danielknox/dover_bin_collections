from __future__ import annotations

DOMAIN = "dover_bin_collections"
DEFAULT_NAME = "Dover Bin Collections"
DEFAULT_BASE_URL = "https://collections.dover.gov.uk"
DEFAULT_SCAN_INTERVAL_HOURS = 6
DEFAULT_TIME_ZONE = "Europe/London"
DEFAULT_EVENT_RETENTION_DAYS = 365
DEVICE_MANUFACTURER = "Bin Collections Portal"
SOURCE_NAME = "Dover resident collections portal"

ATTR_CURRENT = "current"
ATTR_FIRST_SEEN_AT = "first_seen_at"
ATTR_LAST_SEEN_AT = "last_seen_at"
ATTR_SOURCE = "source"

CONF_PROPERTY_ID = "property_id"
CONF_BASE_URL = "base_url"
CONF_SCAN_INTERVAL_HOURS = "scan_interval_hours"

PLATFORMS = ["sensor", "calendar"]

STORAGE_VERSION = 1
STORAGE_KEY_PREFIX = "dover_bin_collections_calendar"
