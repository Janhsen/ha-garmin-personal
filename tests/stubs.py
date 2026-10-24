"""Nachgebaute Home-Assistant-/voluptuous-Module, genug um das ganze Paket (inkl. __init__) zu laden.

Nutzung::

    from stubs import load_full, FakeHass, FakeEntry
    gp = load_full()                      # Paket "gp_full"
    cf = sys.modules["gp_full.config_flow"]

Die Stubs bilden nur das Verhalten nach, das die Integration braucht.
Sie ersetzen bei jedem Aufruf von install() die ``homeassistant.*``-Module in sys.modules;
jede Testdatei ist daher als eigener Prozess zu starten (``python3 -I tests/test_xyz.py``).
"""

from __future__ import annotations

import asyncio
import enum
import importlib.util
import sys
import types
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "garmin_personal"
NAME = "gp_full"


# --------------------------------------------------------------------------- helpers
def stub(name: str, **attrs: Any) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    sys.modules[name] = mod
    parent, _, child = name.rpartition(".")
    if parent and parent in sys.modules:
        setattr(sys.modules[parent], child, mod)
    return mod


class Anything:
    def __init__(self, *a, **k):
        pass

    def __class_getitem__(cls, item):
        return cls


def make_enum(name: str, *members: str):
    return enum.Enum(name, {m: m.lower() for m in members}, type=str)


# --------------------------------------------------------------------------- voluptuous
class Marker:
    def __init__(self, schema, default=None):
        self.schema = schema
        self.default = default  # None == "kein Default"

    def __hash__(self):
        return hash(self.schema)

    def __eq__(self, other):
        return isinstance(other, Marker) and other.schema == self.schema


class Required(Marker):
    pass


class Optional(Marker):
    pass


class Invalid(Exception):
    pass


class Schema:
    def __init__(self, schema):
        self.schema = schema

    def keys(self):
        return {str(k.schema if isinstance(k, Marker) else k): k for k in self.schema}

    def default_of(self, key):
        return self.keys()[key].default


class _Validator:
    def __init__(self, *a, **k):
        self.args, self.kwargs = a, k


class In(_Validator):
    pass


class All(_Validator):
    pass


class Coerce(_Validator):
    pass


class Range(_Validator):
    pass


def _cv_boolean(value):
    """Wie cv.boolean: Strings wie 'false' werden falsch, Unbekanntes ist ungueltig."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        value = value.lower().strip()
        if value in ("1", "true", "yes", "on", "enable"):
            return True
        if value in ("0", "false", "no", "off", "disable"):
            return False
    elif isinstance(value, int | float):
        return bool(value)
    raise Invalid(f"invalid boolean value {value!r}")


# --------------------------------------------------------------------------- exceptions
class HomeAssistantError(Exception):
    """Like the real one: optional translation_* extras; without text str() shows the key."""

    def __init__(self, *args, translation_domain=None, translation_key=None,
                 translation_placeholders=None):
        super().__init__(*args)
        self.translation_domain = translation_domain
        self.translation_key = translation_key
        self.translation_placeholders = translation_placeholders

    def __str__(self):
        return super().__str__() if self.args else str(self.translation_key)


class ServiceValidationError(HomeAssistantError):
    pass


class ConfigEntryAuthFailed(HomeAssistantError):
    pass


class UpdateFailed(Exception):
    pass


class AbortFlow(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


# --------------------------------------------------------------------------- config flow
class ConfigFlow:
    VERSION = 1
    MINOR_VERSION = 1
    configured_unique_ids: set[str] = set()  # Tests setzen das pro Test

    def __init_subclass__(cls, domain=None, **kwargs):
        cls.domain = domain

    def __init__(self):
        self.hass = FakeHass()
        self.unique_id = None
        self.reauth_entry = None
        self.reconfigure_entry = None
        self.updates = []
        self.update_kwargs = []

    def _async_current_entries(self, include_ignore=None):
        return self.hass.config_entries.async_entries()

    async def async_set_unique_id(self, uid):
        self.unique_id = uid

    def _abort_if_unique_id_configured(self):
        if self.unique_id in self.configured_unique_ids:
            raise AbortFlow("already_configured")

    def async_create_entry(self, *, title, data):
        return {"type": "create_entry", "title": title, "data": data}

    def async_show_form(self, *, step_id, data_schema=None, errors=None, description_placeholders=None):
        return {"type": "form", "step_id": step_id, "data_schema": data_schema,
                "errors": errors or {}, "description_placeholders": description_placeholders}

    def async_abort(self, *, reason):
        return {"type": "abort", "reason": reason}

    def async_update_reload_and_abort(self, entry, *, data_updates=None, **kw):
        self.updates.append((entry, data_updates))
        self.update_kwargs.append(kw)
        return {"type": "abort", "reason": "update_reload", "entry": entry, "data_updates": data_updates}

    def _get_reauth_entry(self):
        return self.reauth_entry

    def _get_reconfigure_entry(self):
        return self.reconfigure_entry


class OptionsFlow:
    config_entry = None

    def async_create_entry(self, *, data):
        return {"type": "create_entry", "data": data}

    def async_show_form(self, *, step_id, data_schema=None, errors=None):
        return {"type": "form", "step_id": step_id, "data_schema": data_schema, "errors": errors or {}}


class OptionsFlowWithReload(OptionsFlow):
    """Marker: the real class reloads the entry itself when the options change."""


class Selector:
    def __init__(self, config=None):
        self.config = config


class SelectorConfig:
    def __init__(self, **kw):
        self.__dict__.update(kw)


# --------------------------------------------------------------------------- coordinator & entities
class DataUpdateCoordinator:
    def __class_getitem__(cls, item):
        return cls

    def __init__(self, hass, logger, *, config_entry=None, name=None, update_interval=None):
        self.hass = hass
        self.config_entry = config_entry
        self.name = name
        self.update_interval = update_interval
        self.data = None
        self.last_update_success = True
        self._listeners = []
        self.refresh_requests = 0

    def async_add_listener(self, cb):
        self._listeners.append(cb)

    async def async_refresh(self):
        try:
            self.data = await self._async_update_data()
            self.last_update_success = True
        except UpdateFailed:
            self.last_update_success = False
        for cb in self._listeners:
            cb()

    async def async_config_entry_first_refresh(self):
        await self.async_refresh()

    async def async_request_refresh(self):
        self.refresh_requests += 1


class CoordinatorEntity:
    def __class_getitem__(cls, item):
        return cls

    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.state_writes = 0

    async def async_added_to_hass(self):
        return None

    def async_write_ha_state(self):
        self.state_writes += 1

    def _handle_coordinator_update(self):
        self.state_writes += 1


@dataclass
class CalendarEvent:
    start: object
    end: object
    summary: str
    description: str | None = None
    uid: str | None = None


class CalendarEntity:
    pass


class EventEntity:
    @property
    def triggered(self) -> list[tuple[str, dict]]:
        return self.__dict__.setdefault("_triggered", [])

    def _trigger_event(self, event_type, data=None):
        self.triggered.append((event_type, data))


class BinarySensorEntity:
    pass


class Store:
    """Merkt sich Inhalt; Instanzen sind in Store.instances auffindbar."""

    instances: list["Store"] = []
    preset: dict | None = None

    def __class_getitem__(cls, item):
        return cls

    def __init__(self, hass, version, key):
        self.key = key
        self.saved: list[dict] = []
        Store.instances.append(self)

    async def async_load(self):
        return Store.preset

    async def async_save(self, data):
        self.saved.append(data)

    async def async_remove(self):
        self.removed = True




class RestoreSensor:
    """Stand-in: nothing stored unless a test sets ``_stored``/``_stored_state``."""

    _stored = None
    _stored_state = None

    async def async_added_to_hass(self):
        return None

    async def async_get_last_sensor_data(self):
        return self._stored

    async def async_get_last_state(self):
        return self._stored_state


@dataclass(frozen=True, kw_only=True)
class SensorEntityDescription:
    key: str
    translation_key: str | None = None
    native_unit_of_measurement: str | None = None
    device_class: object = None
    state_class: object = None
    entity_registry_enabled_default: bool = True
    entity_category: object = None
    icon: str | None = None
    suggested_display_precision: int | None = None
    options: object = None


# --------------------------------------------------------------------------- recorder
class StatisticData(dict):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.__dict__.update(kw)


class StatisticMetaData:
    """Variante mit unit_class-Annotation lässt sich per Test umstellen."""

    __annotations__ = {"has_sum": bool, "name": str, "source": str, "statistic_id": str,
                       "unit_of_measurement": str}

    def __init__(self, **kw):
        self.kw = kw


class StatisticMeanType(enum.Enum):
    NONE = 0
    ARITHMETIC = 1


RECORDED: list[tuple[Any, StatisticMetaData, list]] = []


def async_add_external_statistics(hass, metadata, rows):
    RECORDED.append((hass, metadata, rows))


# --------------------------------------------------------------------------- entity registry
class RegistryEntryDisabler(enum.Enum):
    INTEGRATION = "integration"
    USER = "user"


class FakeRegistryEntry:
    def __init__(self, disabled_by=None, unique_id=None, domain="sensor", config_entry_id=None):
        self.disabled_by = disabled_by
        self.unique_id = unique_id
        self.domain = domain
        self.config_entry_id = config_entry_id


class FakeRegistry:
    def __init__(self):
        self.entries: dict[str, FakeRegistryEntry] = {}  # unique_id -> entry
        self.updates: list[tuple[str, dict]] = []

    def async_get_entity_id(self, platform, domain, unique_id):
        return f"{platform}.{unique_id}" if unique_id in self.entries else None

    def async_get(self, entity_id):
        return self.entries.get(entity_id.split(".", 1)[1])

    def async_update_entity(self, entity_id, **kw):
        self.updates.append((entity_id, kw))
        self.entries[entity_id.split(".", 1)[1]].disabled_by = kw.get("disabled_by")


REGISTRY = FakeRegistry()


def _entries_for_entry(registry, entry_id):
    return [e for e in registry.entries.values() if getattr(e, "config_entry_id", None) == entry_id]


# repair issues and interval timers, recorded for tests
ISSUES: dict[tuple[str, str], dict] = {}
TIMERS: list[dict] = []


def _create_issue(hass, domain, issue_id, **kw):
    ISSUES[(domain, issue_id)] = kw


def _delete_issue(hass, domain, issue_id):
    ISSUES.pop((domain, issue_id), None)


def _track_interval(hass, action, interval):
    timer = {"action": action, "interval": interval, "cancelled": False}
    TIMERS.append(timer)

    def cancel():
        timer["cancelled"] = True

    return cancel


def _redact(data, to_redact):
    return {k: ("**REDACTED**" if k in to_redact else v) for k, v in data.items()}


# --------------------------------------------------------------------------- fake hass / entry / call
class FakeConfig:
    def __init__(self, base="/config", allowed=("/config",)):
        self.base = base
        self.allowed = allowed

    def path(self, *parts):
        return "/".join((self.base, *parts))

    def is_allowed_path(self, path):
        return any(str(path) == a or str(path).startswith(a.rstrip("/") + "/") for a in self.allowed)


class FakeServices:
    def __init__(self):
        self.registered: dict[tuple[str, str], dict] = {}

    def has_service(self, domain, name):
        return (domain, name) in self.registered

    def async_register(self, domain, name, handler, schema=None, supports_response=None):
        self.registered[(domain, name)] = {"handler": handler, "schema": schema,
                                           "supports_response": supports_response}


class FakeConfigEntries:
    def __init__(self):
        self.entries: list[Any] = []
        self.updated: list[tuple[Any, dict]] = []
        self.reloaded: list[str] = []
        self.update_kwargs: list[dict] = []
        self.unloaded: list[tuple[Any, list]] = []
        self.forwarded: list[tuple[Any, list]] = []

    def async_entries(self, domain=None):
        return list(self.entries)

    def async_update_entry(self, entry, *, data=None, **kw):
        self.updated.append((entry, data))
        if data is not None:
            entry.data = data
        for attr in ("unique_id", "version", "minor_version", "title", "options"):
            if attr in kw:
                setattr(entry, attr, kw[attr])
        self.update_kwargs.append(kw)

    async def async_unload_platforms(self, entry, platforms):
        self.unloaded.append((entry, list(platforms)))
        return True

    async def async_forward_entry_setups(self, entry, platforms):
        self.forwarded.append((entry, list(platforms)))

    async def async_reload(self, entry_id):
        self.reloaded.append(entry_id)


ConfigEntryState = make_enum("ConfigEntryState", "LOADED", "NOT_LOADED", "SETUP_ERROR", "SETUP_RETRY",
                             "SETUP_IN_PROGRESS", "MIGRATION_ERROR", "FAILED_UNLOAD")


class FakeHass:
    def __init__(self, config=None):
        self.config = config or FakeConfig()
        self.services = FakeServices()
        self.config_entries = FakeConfigEntries()
        self.tasks: list[Any] = []

    async def async_add_executor_job(self, func, *args):
        return func(*args)

    def async_create_task(self, coro):
        self.tasks.append(coro)
        return coro

    async def run_tasks(self):
        tasks, self.tasks = self.tasks, []
        for t in tasks:
            await t


class FakeEntry:
    def __init__(self, entry_id="E1", title="Jan", data=None, options=None, unique_id=None,
                 runtime_data="UNSET", state=None):
        self.entry_id = entry_id
        self.state = state or (ConfigEntryState.LOADED if runtime_data not in ("UNSET", None)
                               else ConfigEntryState.NOT_LOADED)
        self.title = title
        self.data = dict(data or {})
        self.options = dict(options or {})
        self.unique_id = unique_id
        self.version = 1
        self.minor_version = 1
        self.unload_callbacks = []
        if runtime_data != "UNSET":
            self.runtime_data = runtime_data

    def async_on_unload(self, cb):
        self.unload_callbacks.append(cb)

    def add_update_listener(self, cb):
        return cb


class FakeCall:
    def __init__(self, data=None):
        self.data = dict(data or {})


# --------------------------------------------------------------------------- install + load
def install() -> None:
    Platform = make_enum("Platform", "SENSOR", "BINARY_SENSOR", "CALENDAR", "EVENT")
    sensor_dc = make_enum("SensorDeviceClass", "DISTANCE", "DURATION", "ENUM", "TIMESTAMP", "VOLUME", "WEIGHT")
    sensor_sc = make_enum("SensorStateClass", "MEASUREMENT", "TOTAL", "TOTAL_INCREASING")

    stub("voluptuous", Schema=Schema, Required=Required, Optional=Optional, In=In, All=All,
         Coerce=Coerce, Range=Range, Invalid=Invalid)
    stub("homeassistant")
    stub("homeassistant.const", Platform=Platform, PERCENTAGE="%",
         EntityCategory=make_enum("EntityCategory", "DIAGNOSTIC", "CONFIG"),
         UnitOfLength=make_enum("UnitOfLength", "METERS"),
         UnitOfMass=make_enum("UnitOfMass", "KILOGRAMS"),
         UnitOfTime=make_enum("UnitOfTime", "MINUTES", "SECONDS"),
         UnitOfVolume=make_enum("UnitOfVolume", "MILLILITERS"))
    stub("homeassistant.core", HomeAssistant=Anything, ServiceCall=FakeCall, ServiceResponse=dict,
         SupportsResponse=make_enum("SupportsResponse", "ONLY", "OPTIONAL", "NONE"),
         callback=lambda f: f)
    stub("homeassistant.exceptions", ConfigEntryAuthFailed=ConfigEntryAuthFailed,
         HomeAssistantError=HomeAssistantError, ServiceValidationError=ServiceValidationError)
    stub("homeassistant.components")
    stub("homeassistant.components.calendar", CalendarEntity=CalendarEntity, CalendarEvent=CalendarEvent)
    stub("homeassistant.components.sensor", SensorDeviceClass=sensor_dc, SensorStateClass=sensor_sc,
         SensorEntity=type("SensorEntity", (), {}), RestoreSensor=RestoreSensor, SensorEntityDescription=SensorEntityDescription)
    stub("homeassistant.components.binary_sensor",
         BinarySensorDeviceClass=make_enum("BinarySensorDeviceClass", "PROBLEM"),
         BinarySensorEntity=BinarySensorEntity)
    stub("homeassistant.components.event", EventEntity=EventEntity)
    stub("homeassistant.components.recorder")
    stub("homeassistant.components.recorder.models", StatisticData=StatisticData,
         StatisticMetaData=StatisticMetaData, StatisticMeanType=StatisticMeanType)
    stub("homeassistant.components.recorder.statistics",
         async_add_external_statistics=async_add_external_statistics)
    RECORDED.clear()
    stub("homeassistant.helpers")
    stub("homeassistant.helpers.config_validation", string=str, boolean=_cv_boolean, date=date, positive_int=int,
         config_entry_only_config_schema=lambda domain: Schema({}),
         ensure_list=lambda v: v if isinstance(v, list) else [v])
    stub("homeassistant.helpers.entity_registry", async_get=lambda hass: REGISTRY,
         async_entries_for_config_entry=_entries_for_entry,
         RegistryEntryDisabler=RegistryEntryDisabler)
    stub("homeassistant.helpers.aiohttp_client", async_get_clientsession=lambda hass: object())
    stub("homeassistant.helpers.typing", ConfigType=dict, StateType=object)
    stub("homeassistant.helpers.entity_platform", AddEntitiesCallback=Anything)
    stub("homeassistant.helpers.device_registry", DeviceEntryType=make_enum("DeviceEntryType", "SERVICE"),
         DeviceInfo=dict)
    ISSUES.clear()
    stub("homeassistant.helpers.issue_registry",
         IssueSeverity=make_enum("IssueSeverity", "WARNING", "ERROR"),
         async_create_issue=_create_issue, async_delete_issue=_delete_issue)
    TIMERS.clear()
    stub("homeassistant.helpers.event", async_track_time_interval=_track_interval)
    stub("homeassistant.components.diagnostics", async_redact_data=_redact)
    stub("homeassistant.helpers.storage", Store=Store)
    stub("homeassistant.helpers.update_coordinator", CoordinatorEntity=CoordinatorEntity,
         DataUpdateCoordinator=DataUpdateCoordinator, UpdateFailed=UpdateFailed)
    stub("homeassistant.helpers.selector",
         NumberSelector=Selector, NumberSelectorConfig=SelectorConfig,
         NumberSelectorMode=make_enum("NumberSelectorMode", "BOX"),
         SelectSelector=Selector, SelectSelectorConfig=SelectorConfig,
         SelectSelectorMode=make_enum("SelectSelectorMode", "DROPDOWN"),
         TextSelector=Selector, TextSelectorConfig=SelectorConfig,
         TextSelectorType=make_enum("TextSelectorType", "PASSWORD"))
    stub("homeassistant.config_entries", ConfigEntry=Anything, ConfigFlow=ConfigFlow,
         ConfigFlowResult=dict, OptionsFlow=OptionsFlow, OptionsFlowWithReload=OptionsFlowWithReload,
         ConfigEntryState=ConfigEntryState)
    stub("homeassistant.util")
    stub("homeassistant.util.dt",
         now=lambda: datetime.now(UTC), utcnow=lambda: datetime.now(UTC),
         start_of_local_day=lambda d: datetime(d.year, d.month, d.day, tzinfo=UTC))
    # `from homeassistant.helpers import ... entity_registry as er` braucht Attribute am Paket
    helpers = sys.modules["homeassistant.helpers"]
    for sub in ("config_validation", "entity_registry"):
        setattr(helpers, sub, sys.modules[f"homeassistant.helpers.{sub}"])
    Store.instances.clear()
    Store.preset = None
    ConfigFlow.configured_unique_ids = set()
    REGISTRY.entries.clear()
    REGISTRY.updates.clear()


def load_full() -> types.ModuleType:
    """Installiert die Stubs und importiert das echte Paket (inkl. __init__) als ``gp_full``."""
    install()
    for mod in [m for m in sys.modules if m == NAME or m.startswith(NAME + ".")]:
        del sys.modules[mod]
    spec = importlib.util.spec_from_file_location(
        NAME, PKG / "__init__.py", submodule_search_locations=[str(PKG)]
    )
    pkg = importlib.util.module_from_spec(spec)
    sys.modules[NAME] = pkg
    spec.loader.exec_module(pkg)
    for sub in ("config_flow", "services", "event", "binary_sensor", "calendar"):
        importlib.import_module(f"{NAME}.{sub}")
    return pkg


def run(coro):
    return asyncio.run(coro)
