"""Backward-compatibility shim — all functionality moved to torch.fork."""
# TORCH_MODULE: Dev Sandbox (compat shim)
# TORCH_GROUP: Core

from torch.fork import (
    fork_command as sandbox_command,
    _create_fork as _create_sandbox,
    _list_forks as _list_sandboxes,
    _delete_fork as _delete_sandbox,
    _open_fork as _open_sandbox,
    _pick_fork_to_delete,
    _load_registry, _save_registry,
    _dir_size_mb, _next_default_name, _sanitize_name, _format_created,
    _FORKS_JSON as _SANDBOXES_JSON,
)
