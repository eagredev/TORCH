"""Compiler subpackage - TorScript compilation and decompilation."""
import importlib as _importlib


def __getattr__(name):
    """Lazy re-export from compiler.py so `from torch.compiler import X` works."""
    _mod = _importlib.import_module("torch.compiler.compiler")
    try:
        return getattr(_mod, name)
    except AttributeError:
        raise AttributeError(f"module 'torch.compiler' has no attribute {name!r}")
