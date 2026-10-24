"""Load the HA-independent modules without importing the package __init__ (needs Home Assistant)."""

import importlib.util
import sys
import types
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "custom_components" / "garmin_personal"
NAME = "gp_under_test"


def load():
    if NAME in sys.modules:
        return sys.modules[NAME]
    pkg = types.ModuleType(NAME)
    pkg.__path__ = [str(PKG)]
    sys.modules[NAME] = pkg
    for mod in ("const", "api", "values"):
        spec = importlib.util.spec_from_file_location(f"{NAME}.{mod}", PKG / f"{mod}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"{NAME}.{mod}"] = module
        spec.loader.exec_module(module)
        setattr(pkg, mod, module)
    return pkg
