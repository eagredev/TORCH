"""Script templates — generate TorScript beat lists from user input."""
# TORCH_MODULE: Script Templates
# TORCH_GROUP: Script Studio
from torch.colours import GOLD, WHITE, CYAN, DIM, RST
from torch.pickers import (
    pick_flag, pick_trainer, pick_species, pick_item, pick_item_list,
)


# ============================================================
# WEATHER CONSTANTS
# ============================================================

_WEATHER_OPTIONS = [
    ("Sunny",    "WEATHER_SUNNY"),
    ("Rain",     "WEATHER_RAIN"),
    ("Downpour", "WEATHER_RAIN_THUNDERSTORM"),
    ("Drought",  "WEATHER_DROUGHT"),
    ("Fog",      "WEATHER_FOG_HORIZONTAL"),
    ("Snow",     "WEATHER_SNOW"),
]


# ============================================================
# BUILDER FUNCTIONS
# ============================================================

def _build_single_battle(vs, ctx):
    """Single trainer battle with optional flag gate."""
    beats = []
    label = ctx["label"]
    if vs.get("flag"):
        beats.append({"type": "gotoif", "data": {
            "flag": vs["flag"], "condition": "set",
            "target": f"{label}_AlreadyDefeated",
        }})
    beats.append({"type": "battle", "data": {
        "battle_type": "trainerbattle_single",
        "args": f'{vs["trainer"]}, {label}_IntroText, {label}_DefeatText',
    }})
    if vs.get("flag"):
        beats.append({"type": "flag", "data": {
            "action": "set", "flag_name": vs["flag"],
        }})
        beats.append({"type": "flow", "data": {
            "flow_type": "end", "target": "",
        }})
        beats.append({"type": "label", "data": {
            "name": f"{label}_AlreadyDefeated",
        }})
        beats.append({"type": "dialogue", "data": {
            "actor": "player", "text": "Already defeated.",
            "style": "msg",
        }})
    return beats


def _build_double_battle(vs, ctx):
    """Double trainer battle with optional flag gate."""
    beats = []
    label = ctx["label"]
    if vs.get("flag"):
        beats.append({"type": "gotoif", "data": {
            "flag": vs["flag"], "condition": "set",
            "target": f"{label}_AlreadyDefeated",
        }})
    beats.append({"type": "battle", "data": {
        "battle_type": "trainerbattle_double",
        "args": (f'{vs["trainer"]}, {label}_IntroText, '
                 f'{label}_DefeatText, {label}_NotEnoughText'),
    }})
    if vs.get("flag"):
        beats.append({"type": "flag", "data": {
            "action": "set", "flag_name": vs["flag"],
        }})
        beats.append({"type": "flow", "data": {
            "flow_type": "end", "target": "",
        }})
        beats.append({"type": "label", "data": {
            "name": f"{label}_AlreadyDefeated",
        }})
        beats.append({"type": "dialogue", "data": {
            "actor": "player", "text": "Already defeated.",
            "style": "msg",
        }})
    return beats


def _build_nurse_heal(vs, ctx):
    """Standard Pokemon Center nurse interaction."""
    return [
        {"type": "dialogue", "data": {
            "actor": "player", "text": "Would you like me to\\nheal your Pokemon?",
            "style": "msg",
        }},
        {"type": "special", "data": {"function": "HealPlayerParty"}},
        {"type": "waitstate", "data": {}},
        {"type": "dialogue", "data": {
            "actor": "player",
            "text": "Your Pokemon are fighting fit!\\pWe hope to see you again!",
            "style": "msg",
        }},
    ]


def _build_shop(vs, ctx):
    """Shop/mart with item list."""
    greeting = vs.get("greeting", "Welcome! How may I help you?")
    items = vs.get("items", [])
    item_lines = ", ".join(items) if items else "ITEM_POTION"
    beats = [
        {"type": "dialogue", "data": {
            "actor": "player", "text": greeting, "style": "msg",
        }},
        {"type": "pory", "data": {
            "raw_line": f"pokemart({item_lines})",
        }},
        {"type": "dialogue", "data": {
            "actor": "player", "text": "Please come again!",
            "style": "msg",
        }},
    ]
    return beats


def _build_item_gift(vs, ctx):
    """NPC gives player an item, with bag-full fallback."""
    label = ctx["label"]
    beats = []
    if vs.get("flag"):
        beats.append({"type": "gotoif", "data": {
            "flag": vs["flag"], "condition": "set",
            "target": f"{label}_AlreadyGot",
        }})
    dialogue = vs.get("dialogue", "Here, take this!")
    beats.append({"type": "dialogue", "data": {
        "actor": "player", "text": dialogue, "style": "msg",
    }})
    qty = vs.get("quantity", "1") or "1"
    # Validate: must be a positive integer, default to "1" if invalid
    if not qty.isdigit() or int(qty) < 1:
        qty = "1"
    raw = f'giveitem({vs["item"]}, {qty})' if qty != "1" else f'giveitem({vs["item"]})'
    beats.append({"type": "pory", "data": {"raw_line": raw}})
    beats.append({"type": "pory", "data": {
        "raw_line": f"compare(VAR_RESULT, FALSE)",
    }})
    beats.append({"type": "pory", "data": {
        "raw_line": f"goto_if_eq({label}_BagFull)",
    }})
    if vs.get("flag"):
        beats.append({"type": "flag", "data": {
            "action": "set", "flag_name": vs["flag"],
        }})
    beats.append({"type": "flow", "data": {
        "flow_type": "end", "target": "",
    }})
    # Bag full branch
    beats.append({"type": "label", "data": {
        "name": f"{label}_BagFull",
    }})
    beats.append({"type": "dialogue", "data": {
        "actor": "player", "text": "Your bag is full!",
        "style": "msg",
    }})
    beats.append({"type": "flow", "data": {
        "flow_type": "end", "target": "",
    }})
    # Already got branch (if flag used)
    if vs.get("flag"):
        beats.append({"type": "label", "data": {
            "name": f"{label}_AlreadyGot",
        }})
        beats.append({"type": "dialogue", "data": {
            "actor": "player",
            "text": "I hope you're enjoying that gift!",
            "style": "msg",
        }})
    return beats


def _build_sign(vs, ctx):
    """Simple sign/readable text."""
    return [
        {"type": "pory", "data": {
            "raw_line": f'msgbox(format("{vs["text"]}"), MSGBOX_SIGN)',
        }},
    ]


def _build_weather(vs, ctx):
    """Change map weather."""
    weather_const = vs["weather"]
    return [
        {"type": "pory", "data": {"raw_line": f"setweather({weather_const})"}},
        {"type": "pory", "data": {"raw_line": "doweather()"}},
    ]


def _build_trade(vs, ctx):
    """In-game Pokemon trade NPC."""
    label = ctx["label"]
    beats = []
    if vs.get("flag"):
        beats.append({"type": "gotoif", "data": {
            "flag": vs["flag"], "condition": "set",
            "target": f"{label}_AlreadyTraded",
        }})
    beats.append({"type": "dialogue", "data": {
        "actor": "player",
        "text": f"Want to trade your\\n{vs['wanted_species']} for my {vs['offered_species']}?",
        "style": "msg",
    }})
    beats.append({"type": "pory", "data": {
        "raw_line": "special(ChoosePartyMon)",
    }})
    beats.append({"type": "waitstate", "data": {}})
    beats.append({"type": "pory", "data": {
        "raw_line": f"compare(VAR_0x8004, PARTY_SIZE)",
    }})
    beats.append({"type": "pory", "data": {
        "raw_line": f"goto_if_ge({label}_Declined)",
    }})
    beats.append({"type": "pory", "data": {
        "raw_line": f"special(CreateInGameTradePokemon)",
    }})
    beats.append({"type": "pory", "data": {
        "raw_line": f"special(DoInGameTradeScene)",
    }})
    beats.append({"type": "waitstate", "data": {}})
    if vs.get("flag"):
        beats.append({"type": "flag", "data": {
            "action": "set", "flag_name": vs["flag"],
        }})
    beats.append({"type": "flow", "data": {
        "flow_type": "end", "target": "",
    }})
    # Declined branch
    beats.append({"type": "label", "data": {
        "name": f"{label}_Declined",
    }})
    beats.append({"type": "dialogue", "data": {
        "actor": "player", "text": "That's a shame. Maybe next time!",
        "style": "msg",
    }})
    beats.append({"type": "flow", "data": {
        "flow_type": "end", "target": "",
    }})
    # Already traded branch
    if vs.get("flag"):
        beats.append({"type": "label", "data": {
            "name": f"{label}_AlreadyTraded",
        }})
        beats.append({"type": "dialogue", "data": {
            "actor": "player",
            "text": f"How's that {vs['offered_species']} treating you?",
            "style": "msg",
        }})
    return beats


def _build_move_tutor(vs, ctx):
    """Move Tutor NPC."""
    label = ctx["label"]
    move_name = vs.get("move_name", "MOVE_NONE")
    beats = []
    if vs.get("flag"):
        beats.append({"type": "gotoif", "data": {
            "flag": vs["flag"], "condition": "set",
            "target": f"{label}_AlreadyTaught",
        }})
    beats.append({"type": "dialogue", "data": {
        "actor": "player",
        "text": f"Want me to teach one of\\nyour Pokemon a move?",
        "style": "msg",
    }})
    beats.append({"type": "pory", "data": {
        "raw_line": f"setvar(VAR_0x8005, {move_name})",
    }})
    beats.append({"type": "pory", "data": {
        "raw_line": "special(ChooseMonForMoveTutor)",
    }})
    beats.append({"type": "waitstate", "data": {}})
    beats.append({"type": "pory", "data": {
        "raw_line": "compare(VAR_RESULT, 0)",
    }})
    beats.append({"type": "pory", "data": {
        "raw_line": f"goto_if_eq({label}_Declined)",
    }})
    if vs.get("flag"):
        beats.append({"type": "flag", "data": {
            "action": "set", "flag_name": vs["flag"],
        }})
    beats.append({"type": "flow", "data": {
        "flow_type": "end", "target": "",
    }})
    # Declined
    beats.append({"type": "label", "data": {
        "name": f"{label}_Declined",
    }})
    beats.append({"type": "dialogue", "data": {
        "actor": "player", "text": "Come back if you change your mind!",
        "style": "msg",
    }})
    beats.append({"type": "flow", "data": {
        "flow_type": "end", "target": "",
    }})
    # Already taught
    if vs.get("flag"):
        beats.append({"type": "label", "data": {
            "name": f"{label}_AlreadyTaught",
        }})
        beats.append({"type": "dialogue", "data": {
            "actor": "player",
            "text": "That move is really something, isn't it?",
            "style": "msg",
        }})
    return beats


# ============================================================
# TEMPLATE DEFINITIONS
# ============================================================

TEMPLATE_SINGLE_BATTLE = {
    "id": "single_battle",
    "name": "Single Battle",
    "description": "Trainer battle with intro/defeat text and flag gate",
    "category": "npc",
    "trigger": "npc",
    "variables": [
        {"key": "trainer", "type": "trainer",
         "prompt": "Trainer constant", "required": True},
        {"key": "flag", "type": "flag",
         "prompt": "Flag to prevent rematch (Enter to skip)", "required": False},
    ],
    "builder": _build_single_battle,
}

TEMPLATE_DOUBLE_BATTLE = {
    "id": "double_battle",
    "name": "Double Battle",
    "description": "Double trainer battle with not-enough-Pokemon check",
    "category": "npc",
    "trigger": "npc",
    "variables": [
        {"key": "trainer", "type": "trainer",
         "prompt": "Trainer constant", "required": True},
        {"key": "flag", "type": "flag",
         "prompt": "Flag to prevent rematch (Enter to skip)", "required": False},
    ],
    "builder": _build_double_battle,
}

TEMPLATE_NURSE_HEAL = {
    "id": "nurse_heal",
    "name": "Nurse Heal",
    "description": "Pokemon Center nurse interaction",
    "category": "npc",
    "trigger": "npc",
    "variables": [],
    "builder": _build_nurse_heal,
}

TEMPLATE_SHOP = {
    "id": "shop",
    "name": "Shop / Mart",
    "description": "Shopkeeper with item list",
    "category": "npc",
    "trigger": "npc",
    "variables": [
        {"key": "items", "type": "item_list",
         "prompt": "Items to sell", "required": True},
        {"key": "greeting", "type": "text",
         "prompt": "Greeting dialogue",
         "default": "Welcome! How may I help you?", "required": False},
    ],
    "builder": _build_shop,
}

TEMPLATE_ITEM_GIFT = {
    "id": "item_gift",
    "name": "Item Gift",
    "description": "NPC gives player an item with bag-full check",
    "category": "event",
    "trigger": "npc",
    "variables": [
        {"key": "item", "type": "item",
         "prompt": "Item to give", "required": True},
        {"key": "quantity", "type": "text",
         "prompt": "Quantity (default 1)", "default": "1", "required": False},
        {"key": "flag", "type": "flag",
         "prompt": "Flag (prevent re-giving)", "required": False},
        {"key": "dialogue", "type": "text",
         "prompt": "Gift dialogue", "default": "Here, take this!",
         "required": False},
    ],
    "builder": _build_item_gift,
}

TEMPLATE_SIGN = {
    "id": "sign",
    "name": "Sign / Readable",
    "description": "Simple sign text",
    "category": "utility",
    "trigger": "npc",
    "variables": [
        {"key": "text", "type": "text",
         "prompt": "Sign text", "required": True},
    ],
    "builder": _build_sign,
}

TEMPLATE_WEATHER = {
    "id": "weather",
    "name": "Weather Setter",
    "description": "Change map weather",
    "category": "utility",
    "trigger": "none",
    "variables": [
        {"key": "weather", "type": "weather",
         "prompt": "Weather type", "required": True},
    ],
    "builder": _build_weather,
}

TEMPLATE_TRADE = {
    "id": "trade",
    "name": "Trade NPC",
    "description": "In-game Pokemon trade",
    "category": "npc",
    "trigger": "npc",
    "variables": [
        {"key": "wanted_species", "type": "species",
         "prompt": "Species player must offer", "required": True},
        {"key": "offered_species", "type": "species",
         "prompt": "Species NPC will trade", "required": True},
        {"key": "flag", "type": "flag",
         "prompt": "Flag (one-time trade)", "required": False},
    ],
    "builder": _build_trade,
}

TEMPLATE_MOVE_TUTOR = {
    "id": "move_tutor",
    "name": "Move Tutor",
    "description": "Teach a move to player's Pokemon",
    "category": "npc",
    "trigger": "npc",
    "variables": [
        {"key": "move_name", "type": "text",
         "prompt": "Move constant (e.g. MOVE_THUNDERBOLT)", "required": True},
        {"key": "flag", "type": "flag",
         "prompt": "Flag (one-time tutor)", "required": False},
    ],
    "builder": _build_move_tutor,
}


# ============================================================
# TEMPLATE REGISTRY
# ============================================================

TEMPLATES = [
    TEMPLATE_SINGLE_BATTLE,
    TEMPLATE_DOUBLE_BATTLE,
    TEMPLATE_NURSE_HEAL,
    TEMPLATE_SHOP,
    TEMPLATE_ITEM_GIFT,
    TEMPLATE_SIGN,
    TEMPLATE_WEATHER,
    TEMPLATE_TRADE,
    TEMPLATE_MOVE_TUTOR,
]


# ============================================================
# CATEGORY ORDERING
# ============================================================

_CATEGORY_ORDER = ["npc", "event", "utility"]

_CATEGORY_LABELS = {
    "npc": "NPC Scripts",
    "event": "Events",
    "utility": "Utility",
}


# ============================================================
# TEMPLATE PICKER
# ============================================================

def pick_template(category=None):
    """Show templates grouped by category. Returns a template dict or None."""
    if category:
        pool = [t for t in TEMPLATES if t["category"] == category]
    else:
        pool = list(TEMPLATES)

    if not pool:
        print(f"  {DIM}(no templates available){RST}")
        return None

    print()
    print(f"  {WHITE}Script Templates:{RST}")

    # Group by category in display order
    numbered = []
    for cat in _CATEGORY_ORDER:
        group = [t for t in pool if t["category"] == cat]
        if not group:
            continue
        label = _CATEGORY_LABELS.get(cat, cat.title())
        print(f"    {CYAN}{label}{RST}")
        for t in group:
            numbered.append(t)
            idx = len(numbered)
            print(f"      {GOLD}[{idx:>2}]{RST} {WHITE}{t['name']}{RST}"
                  f"  {DIM}-- {t['description']}{RST}")

    print()
    print(f"  {GOLD}[#]{RST} Select template    {GOLD}[q]{RST} Cancel")
    print()
    raw = input("  > ").strip()
    if not raw or raw.lower() == "q":
        return None
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(numbered):
            return numbered[idx]
        print(f"  {DIM}Pick a number from 1-{len(numbered)}.{RST}")
    except ValueError:
        pass
    return None


# ============================================================
# VARIABLE COLLECTOR
# ============================================================

def _collect_text(var_def, game_path):
    """Collect a free-text value with optional default."""
    prompt = var_def.get("prompt", var_def["key"])
    default = var_def.get("default")
    suffix = f" [{default}]" if default else ""
    raw = input(f"  {prompt}{suffix} > ").strip()
    if not raw:
        return default if default else None
    return raw


def _collect_numbered_menu(prompt, options):
    """Show a numbered menu and return the selected value, or None."""
    print(f"  {prompt}:")
    for i, (label, value) in enumerate(options, 1):
        print(f"    {GOLD}[{i}]{RST} {label}")
    print()
    raw = input("  > ").strip()
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(options):
            return options[idx][1]
    except ValueError:
        pass
    return None


def _collect_weather(var_def, game_path):
    """Collect a weather constant from numbered menu."""
    return _collect_numbered_menu(
        var_def.get("prompt", "Weather type"), _WEATHER_OPTIONS)


def _collect_choice(var_def, game_path):
    """Collect from a list of options."""
    options = [(o, o) for o in var_def.get("options", [])]
    return _collect_numbered_menu(
        var_def.get("prompt", "Choice"), options)


# Dispatch: variable type -> collector function(var_def, game_path)
_VAR_COLLECTORS = {
    "flag":      lambda vd, gp: pick_flag(gp),
    "trainer":   lambda vd, gp: pick_trainer(gp),
    "species":   lambda vd, gp: pick_species(gp),
    "item":      lambda vd, gp: pick_item(gp),
    "item_list": lambda vd, gp: pick_item_list(gp),
    "text":      _collect_text,
    "weather":   _collect_weather,
    "choice":    _collect_choice,
}


def _collect_variable(var_def, game_path):
    """Collect a single variable value based on its type.

    Returns the collected value, or None if skipped/cancelled.
    """
    vtype = var_def["type"]
    collector = _VAR_COLLECTORS.get(vtype)
    if collector:
        return collector(var_def, game_path)
    # Fallback: free text
    prompt = var_def.get("prompt", var_def["key"])
    raw = input(f"  {prompt} > ").strip()
    return raw or None


# ============================================================
# TEMPLATE RUNNER
# ============================================================

def run_template(template, ctx):
    """Collect variables and run the builder. Returns list of beat dicts."""
    game_path = ctx.get("game_path")

    print()
    print(f"  {WHITE}{template['name']}{RST}  {DIM}-- {template['description']}{RST}")
    print()

    collected = {}
    for var_def in template["variables"]:
        value = _collect_variable(var_def, game_path)
        if value is None and var_def.get("required", True):
            print(f"  {DIM}Cancelled.{RST}")
            return []
        collected[var_def["key"]] = value

    beats = template["builder"](collected, ctx)
    if beats:
        print()
        print(f"  {DIM}Generated {len(beats)} beat{'s' if len(beats) != 1 else ''}.{RST}")
    return beats


def run_template_wizard(game_path, map_name, label, cast=None):
    """Full wizard wrapper — pick template then run it.

    Returns list of beat dicts, or empty list if cancelled.
    """
    template = pick_template()
    if not template:
        return []

    ctx = {
        "label": label,
        "map_name": map_name,
        "game_path": game_path,
        "cast": cast or {},
    }
    return run_template(template, ctx)
