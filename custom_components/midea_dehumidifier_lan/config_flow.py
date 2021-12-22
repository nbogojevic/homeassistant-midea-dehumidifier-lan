"""Config flow for Midea Dehumidifier (Local) integration."""
from __future__ import annotations

import ipaddress
import logging
from typing import Any

from homeassistant import config_entries, data_entry_flow
from homeassistant.const import (
    CONF_DEVICES,
    CONF_ID,
    CONF_IP_ADDRESS,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_TOKEN,
    CONF_TYPE,
    CONF_USERNAME,
)
import voluptuous as vol

from midea_beautiful_dehumidifier import connect_to_cloud, find_appliances
from midea_beautiful_dehumidifier.cloud import MideaCloud
from midea_beautiful_dehumidifier.exceptions import CloudAuthenticationError
from midea_beautiful_dehumidifier.lan import LanDevice, get_appliance_state
from midea_beautiful_dehumidifier.midea import (
    DEFAULT_APP_ID,
    DEFAULT_APPKEY,
    SUPPORTED_APPS,
)

from .const import (
    CONF_ADVANCED_OPTIONS,
    CONF_APPID,
    CONF_APPKEY,
    CONF_IGNORE_APPLIANCE,
    CONF_MOBILE_APP,
    CONF_NETWORK_RANGE,
    CONF_TOKEN_KEY,
    DEFAULT_APP,
    DEFAULT_PASSWORD,
    DEFAULT_USERNAME,
    DOMAIN,
    IGNORED_IP_ADDRESS,
    NAME,
    TAG_CAUSE,
    TAG_ID,
    TAG_INTEGRATION,
    TAG_NAME,
)

_LOGGER = logging.getLogger(__name__)


class FlowException(Exception):
    def __init__(self, message, cause=None) -> None:
        self.message = message
        self.cause = cause


def connect_and_discover(flow: MideaLocalConfigFlow):
    """Validates that cloud credentials are valid and discovers local appliances"""

    cloud = connect_to_cloud(
        account=flow._conf[CONF_USERNAME],
        password=flow._conf[CONF_PASSWORD],
        appkey=flow._conf[CONF_APPKEY],
        appid=flow._conf[CONF_APPID],
    )
    if cloud is None:
        raise FlowException("no_cloud")

    networks = flow._conf.get(CONF_NETWORK_RANGE) or []
    if isinstance(networks, str):
        networks = [networks]
    appliances = find_appliances(cloud, networks=networks)
    flow._appliances = appliances
    flow._cloud = cloud


def validate_appliance(cloud: MideaCloud, appliance: LanDevice):
    """
    Validates that appliance configuration is correct and matches physical
    device
    """
    if appliance.ip == IGNORED_IP_ADDRESS or appliance.ip is None:
        _LOGGER.debug("Ignored appliance with id=%s", appliance.id)
        return True
    try:
        ipaddress.IPv4Address(appliance.ip)
    except Exception as ex:
        raise FlowException("invalid_ip_address", appliance.ip) from ex
    discovered = get_appliance_state(ip=appliance.ip, cloud=cloud)
    if discovered is not None:
        appliance.update(discovered)
        return True
    raise FlowException("not_discovered", appliance.ip)


class MideaLocalConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """
    Configuration flow for Midea dehumidifiers on local network uses discovery based on
    Midea cloud, so it first requires credentials for it.
    If some appliances are registered in the cloud, but not discovered, configuration
    flow will prompt for additional information.
    """

    def __init__(self):
        self._cloud_credentials: dict | None = None
        self._cloud: MideaCloud | None = None
        self._appliance_idx = -1
        self._appliances: list[LanDevice] = []
        self._appliance_conf = []
        self._conf = {}
        self._advanced_options = False

    async def _validate_discovery_phase(self, user_input: dict[str, Any] | None):

        if self._advanced_options:
            if self._conf is not None and user_input is not None:
                if CONF_APPKEY not in user_input or CONF_APPID not in user_input:
                    raise FlowException("invalid_appkey")
                self._conf[CONF_APPKEY] = user_input[CONF_APPKEY]
                self._conf[CONF_APPID] = user_input[CONF_APPID]
                if network_range := user_input.get(CONF_NETWORK_RANGE):
                    try:
                        ipaddress.IPv4Network(network_range, strict=False)
                    except Exception as ex:
                        raise FlowException("invalid_ip_range", network_range) from ex
                    self._conf[CONF_NETWORK_RANGE] = network_range
            else:
                _LOGGER.error("Expected previous input when on advanced options page")
                raise FlowException("invalid_state")
        else:
            if user_input is None:
                _LOGGER.error("Expected user input")
                raise FlowException("invalid_state")
            self._conf = user_input
            if app := user_input.get(CONF_MOBILE_APP):
                if apps := SUPPORTED_APPS.get(app):
                    self._conf[CONF_APPKEY] = apps[CONF_APPKEY]
                    self._conf[CONF_APPID] = apps[CONF_APPID]
                else:
                    raise FlowException("invalid_app_name", app)
            else:
                self._conf[CONF_APPKEY] = DEFAULT_APPKEY
                self._conf[CONF_APPID] = DEFAULT_APP_ID
            if user_input[CONF_ADVANCED_OPTIONS]:
                return await self.async_step_advanced_options()

        self._appliance_idx = -1

        await self.hass.async_add_executor_job(connect_and_discover, self)
        for i, appliance in enumerate(self._appliances):
            if not appliance.ip:
                self._appliance_idx = i
                break
        if self._appliance_idx >= 0:
            return await self.async_step_unreachable_appliance()

        return await self._async_add_entry()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        self._advanced_options = False
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        errors: dict = {}
        self._cause = ""

        username = DEFAULT_USERNAME
        password = DEFAULT_PASSWORD
        app = DEFAULT_APP
        if user_input is not None:
            try:
                username = user_input.get(CONF_USERNAME) or DEFAULT_USERNAME
                password = user_input.get(CONF_PASSWORD) or DEFAULT_PASSWORD
                app = user_input.get(CONF_MOBILE_APP) or DEFAULT_APP
                return await self._validate_discovery_phase(user_input)
            except FlowException as ex:
                self._cause = ex.cause
                errors["base"] = ex.message
            except CloudAuthenticationError as ex:
                self._cause = f"{ex.error_code} - {ex.message}"
                errors["base"] = "invalid_auth"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME, default=username): str,
                    vol.Required(CONF_PASSWORD, default=password): str,
                    vol.Optional(CONF_MOBILE_APP, default=app): vol.In(
                        ["NetHome", "MideaAir"]
                    ),
                    vol.Required(CONF_ADVANCED_OPTIONS, default=False): bool,
                }
            ),
            description_placeholders=self.placeholders(),
            errors=errors,
        )

    async def async_step_advanced_options(
        self, user_input: dict[str, Any] | None = None
    ):
        errors: dict = {}
        self._cause = ""
        self._advanced_options = True
        username = self._conf.get(CONF_USERNAME) or DEFAULT_USERNAME
        password = self._conf.get(CONF_PASSWORD) or DEFAULT_PASSWORD
        appkey = DEFAULT_APPKEY
        appid = DEFAULT_APP_ID
        network_range = ""
        if user_input is not None:
            try:
                username = user_input.get(CONF_USERNAME) or username
                password = user_input.get(CONF_PASSWORD) or password
                appkey = user_input.get(CONF_APPKEY) or DEFAULT_APPKEY
                appid = int(user_input.get(CONF_APPID) or DEFAULT_APP_ID)
                network_range = user_input.get(CONF_NETWORK_RANGE) or ""
                return await self._validate_discovery_phase(user_input)
            except FlowException as ex:
                self._cause = ex.cause
                errors["base"] = ex.message
            except CloudAuthenticationError as ex:
                self._cause = f"{ex.error_code} - {ex.message}"
                errors["base"] = "invalid_auth"

        return self.async_show_form(
            step_id="advanced_options",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME, default=username): str,
                    vol.Required(CONF_PASSWORD, default=password): str,
                    vol.Required(CONF_APPKEY, default=appkey): str,
                    vol.Required(CONF_APPID, default=appid): int,
                    vol.Optional(CONF_NETWORK_RANGE, default=network_range): str,
                }
            ),
            description_placeholders=self.placeholders(),
            errors=errors,
        )

    async def async_step_unreachable_appliance(
        self, user_input: dict[str, Any] | None = None
    ):
        """Manage the appliances that were not discovered automatically on LAN."""
        errors: dict = {}
        self._cause = ""
        appliance = self._appliances[self._appliance_idx]

        if user_input is not None:
            appliance.ip = user_input.get(CONF_IP_ADDRESS)
            if not appliance.ip:
                appliance.ip = IGNORED_IP_ADDRESS
            appliance.name = user_input[CONF_NAME]
            appliance.token = user_input[CONF_TOKEN] if CONF_TOKEN in user_input else ""
            appliance.key = (
                user_input[CONF_TOKEN_KEY] if CONF_TOKEN_KEY in user_input else ""
            )
            try:
                await self.hass.async_add_executor_job(
                    validate_appliance,
                    self._cloud,
                    appliance,
                )
                # Find next unreachable appliance
                self._appliance_idx = self._appliance_idx + 1
                while self._appliance_idx < len(self._appliances):
                    if self._appliances[self._appliance_idx].ip is None:
                        return await self.async_step_unreachable_appliance()
                    self._appliance_idx = self._appliance_idx + 1

                # If no unreachable appliances, create entry
                if self._appliance_idx >= len(self._appliances):
                    return await self._async_add_entry()
                appliance = self._appliances[self._appliance_idx]

            except FlowException as ex:
                self._cause = ex.cause
                errors["base"] = ex.message

        name = appliance.name
        return self.async_show_form(
            step_id="unreachable_appliance",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_IGNORE_APPLIANCE, default=False): bool,
                    vol.Optional(CONF_IP_ADDRESS, default=IGNORED_IP_ADDRESS): str,
                    vol.Optional(CONF_NAME, default=name): str,
                    vol.Optional(CONF_TOKEN): str,
                    vol.Optional(CONF_TOKEN_KEY): str,
                }
            ),
            description_placeholders=self.placeholders(appliance=appliance),
            errors=errors,
        )

    def placeholders(self, appliance: LanDevice = None):
        placeholders = {
            TAG_CAUSE: self._cause or "",
            TAG_INTEGRATION: NAME,
        }
        if appliance:
            placeholders[TAG_ID] = appliance.id
            placeholders[TAG_NAME] = appliance.name
        return placeholders

    async def _async_add_entry(self):
        if self._conf is not None:
            self._appliance_conf = []
            for appliance in self._appliances:
                if appliance.ip and appliance.ip != IGNORED_IP_ADDRESS:
                    self._appliance_conf.append(
                        {
                            CONF_IP_ADDRESS: appliance.ip,
                            CONF_ID: appliance.id,
                            CONF_NAME: appliance.name,
                            CONF_TYPE: appliance.type,
                            CONF_TOKEN: appliance.token,
                            CONF_TOKEN_KEY: appliance.key,
                        }
                    )
            existing_entry = await self.async_set_unique_id(self._conf[CONF_USERNAME])
            self._conf[CONF_DEVICES] = self._appliance_conf
            if existing_entry:
                self.hass.config_entries.async_update_entry(
                    existing_entry,
                    data=self._conf,
                )
                # Reload the config entry otherwise devices will remain unavailable
                self.hass.async_create_task(
                    self.hass.config_entries.async_reload(existing_entry.entry_id)
                )

                return self.async_abort(reason="reauth_successful")
            else:
                return self.async_create_entry(
                    title="Midea Dehumidifiers",
                    data=self._conf,
                )
        else:
            _LOGGER.error("Configuration should have been set before reaching this!")
            raise FlowException("unexpected_state")