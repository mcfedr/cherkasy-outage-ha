"""Base entity: one service device per account, updated by the runtime."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .coordinator import OutageRuntime


class OutageEntity(Entity):
    """Shared plumbing; subclasses only describe their state."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, runtime: OutageRuntime, key: str) -> None:
        self.runtime = runtime
        entry = runtime.entry
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            translation_key="outages",
            manufacturer="Cherkasyoblenergo",
            model=entry.title,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://www.cherkasyoblenergo.com/off",
        )

    @property
    def available(self) -> bool:
        return self.runtime.schedule.last_update_success or self.runtime.account.last_update_success

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.runtime.async_add_listener(self.async_write_ha_state))
