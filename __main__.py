"""TORCH entry point - bootstraps into src/torch."""
import os
import sys
import runpy

# Add src/ to the path so `from torch.X` imports resolve correctly.
_src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

runpy.run_module("torch", run_name="__main__", alter_sys=True)
