"""Test-only package stubs for modules that do not need a live HA instance."""

from datetime import datetime, timezone
from pathlib import Path
import sys
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
CUSTOM_COMPONENTS = ModuleType("custom_components")
CUSTOM_COMPONENTS.__path__ = [str(ROOT / "custom_components")]
DEKUDEALS = ModuleType("custom_components.dekudeals")
DEKUDEALS.__path__ = [str(ROOT / "custom_components" / "dekudeals")]
sys.modules.setdefault("custom_components", CUSTOM_COMPONENTS)
sys.modules.setdefault("custom_components.dekudeals", DEKUDEALS)

homeassistant = ModuleType("homeassistant")
homeassistant.__path__ = []
core = ModuleType("homeassistant.core")
core.HomeAssistant = type("HomeAssistant", (), {})
helpers = ModuleType("homeassistant.helpers")
helpers.__path__ = []
storage = ModuleType("homeassistant.helpers.storage")
storage.Store = type("Store", (), {})
util = ModuleType("homeassistant.util")
util.__path__ = []
dt = ModuleType("homeassistant.util.dt")
dt.utcnow = lambda: datetime.now(timezone.utc)
sys.modules.setdefault("homeassistant", homeassistant)
sys.modules.setdefault("homeassistant.core", core)

components = ModuleType("homeassistant.components")
components.__path__ = []
http = ModuleType("homeassistant.components.http")
http.HomeAssistantView = type("HomeAssistantView", (), {})
components_http_helpers = ModuleType("homeassistant.helpers.aiohttp_client")
components_http_helpers.async_get_clientsession = lambda hass: None
sys.modules.setdefault("homeassistant.components", components)
sys.modules.setdefault("homeassistant.components.http", http)
sys.modules.setdefault("homeassistant.helpers.aiohttp_client", components_http_helpers)
sys.modules.setdefault("homeassistant.helpers", helpers)
sys.modules.setdefault("homeassistant.helpers.storage", storage)
sys.modules.setdefault("homeassistant.util", util)
sys.modules.setdefault("homeassistant.util.dt", dt)
