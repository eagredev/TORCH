"""Studio subpackage - workspace, tools, and asset management."""
import importlib as _importlib


def __getattr__(name):
    """Lazy re-export from studio.py so `from torch.studio import X` works."""
    _mod = _importlib.import_module("torch.studio.studio")
    try:
        return getattr(_mod, name)
    except AttributeError:
        raise AttributeError(f"module 'torch.studio' has no attribute {name!r}")
