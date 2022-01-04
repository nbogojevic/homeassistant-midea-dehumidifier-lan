"""Adds dehumidifer entity for each dehumidifer appliance."""

import logging
from typing import Final

from homeassistant.components.humidifier import HumidifierDeviceClass, HumidifierEntity
from homeassistant.components.humidifier.const import (
    SUPPORT_MODES,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.midea_dehumidifier_lan import (
    ApplianceEntity,
    ApplianceUpdateCoordinator,
    Hub,
)
from custom_components.midea_dehumidifier_lan.const import (
    DOMAIN,
    MAX_TARGET_HUMIDITY,
    MIN_TARGET_HUMIDITY,
)


_LOGGER = logging.getLogger(__name__)

MODE_SET: Final = "Set"
MODE_DRY: Final = "Dry"
MODE_SMART: Final = "Smart"
MODE_CONTINOUS: Final = "Continuous"
MODE_PURIFIER: Final = "Purifier"
MODE_ANTIMOULD: Final = "Antimould"
MODE_FAN: Final = "Fan"

_ATTR_RUNNING: Final = "running"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Sets up dehumidifier entites"""
    hub: Hub = hass.data[DOMAIN][config_entry.entry_id]

    async_add_entities(
        DehumidifierEntity(c) for c in hub.coordinators if c.is_dehumidifier()
    )


class DehumidifierEntity(ApplianceEntity, HumidifierEntity):
    """(de)Humidifer entity for Midea appliances """

    def __init__(self, coordinator: ApplianceUpdateCoordinator) -> None:
        super().__init__(coordinator)
        supports = getattr(coordinator.appliance.state, "supports", {})

        self.modes = [MODE_SET]
        if supports.get("auto", 0):
            self.modes.append(MODE_SMART)
        self.modes.append(MODE_CONTINOUS)
        if supports.get("dry_clothes", 0):
            self.modes.append(MODE_DRY)

        more_modes = supports.get("mode", "0")
        if more_modes == 1:
            self.modes.append(MODE_PURIFIER)
        elif more_modes == 2:
            self.modes.append(MODE_ANTIMOULD)
        elif more_modes == 3:
            self.modes.append(MODE_PURIFIER)
            self.modes.append(MODE_ANTIMOULD)
        elif more_modes == 4:
            self.modes.append(MODE_FAN)

    @property
    def name_suffix(self) -> str:
        """Suffix to append to entity name"""
        return ""

    @property
    def is_on(self) -> bool:
        return getattr(self.appliance.state, _ATTR_RUNNING, False)

    @property
    def device_class(self) -> str:
        return HumidifierDeviceClass.DEHUMIDIFIER

    @property
    def target_humidity(self) -> int:
        return int(getattr(self.appliance.state, "target_humidity", 0))

    @property
    def supported_features(self) -> int:
        return SUPPORT_MODES

    @property
    def available_modes(self) -> list[str]:
        return self.modes

    @property
    def mode(self):
        curr_mode = getattr(self.appliance.state, "mode", 1)
        if curr_mode == 1:
            return MODE_SET
        if curr_mode == 2:
            return MODE_CONTINOUS
        if curr_mode == 3:
            return MODE_SMART
        if curr_mode == 4:
            return MODE_DRY
        if curr_mode == 6:
            return MODE_PURIFIER
        if curr_mode == 7:
            return MODE_ANTIMOULD
        _LOGGER.warning("Unknown mode %d", curr_mode)
        return MODE_SET

    @property
    def min_humidity(self) -> int:
        """Return the min humidity that can be set."""
        return MIN_TARGET_HUMIDITY

    @property
    def max_humidity(self) -> int:
        """Return the max humidity that can be set."""
        return MAX_TARGET_HUMIDITY

    def turn_on(self, **kwargs) -> None:
        """Turn the entity on."""
        self.apply(_ATTR_RUNNING, True)

    def turn_off(self, **kwargs) -> None:
        """Turn the entity off."""
        self.apply(_ATTR_RUNNING, False)

    def set_mode(self, mode) -> None:
        """Set new target preset mode."""
        if mode == MODE_SET:
            curr_mode = 1
        elif mode == MODE_CONTINOUS:
            curr_mode = 2
        elif mode == MODE_SMART:
            curr_mode = 3
        elif mode == MODE_DRY:
            curr_mode = 4
        elif mode == MODE_PURIFIER:
            curr_mode = 6
        elif mode == MODE_ANTIMOULD:
            curr_mode = 7
        else:
            _LOGGER.warning("Unsupported dehumidifer mode %s", mode)
            curr_mode = 1
        self.apply("mode", curr_mode)

    def set_humidity(self, humidity) -> None:
        """Set new target humidity."""
        self.apply("target_humidity", humidity)
