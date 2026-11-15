"""Load pure integration modules without requiring the HA runtime in unit tests."""

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
