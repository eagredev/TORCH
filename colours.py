"""Shared ANSI colour palette for TORCH."""
# TORCH_MODULE: Colours
# TORCH_GROUP: Core

# --- Core palette (used by 15+ modules) ---
GOLD = "\033[1;33m"
WHITE = "\033[1;37m"
CYAN = "\033[36m"
GREEN = "\033[32m"
DIM = "\033[2m"
RST = "\033[0m"

# --- Extended palette ---
RED = "\033[31m"
BOLD_RED = "\033[1;31m"
BLUE = "\033[34m"
DGOLD = "\033[33m"         # Dark/regular gold (not bold)
BOLD = "\033[1m"


# --- Shared UI elements ---
BAR = f"  {GOLD}" + "\u2501" * 49 + RST

# --- Utility ---
def strip_ansi(text):
    """Remove ANSI escape sequences from text. Returns plain string."""
    import re
    return re.sub(r'\033\[[0-9;]*m', '', text)
