"""SCORCH subpackage - vanilla content removal."""
import importlib as _importlib


def __getattr__(name):
    """Lazy re-export from scorch.py so `from torch.scorch import X` works."""
    _mod = _importlib.import_module("torch.scorch.scorch")
    try:
        return getattr(_mod, name)
    except AttributeError:
        raise AttributeError(f"module 'torch.scorch' has no attribute {name!r}")
