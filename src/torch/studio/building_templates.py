"""TORCH Building Templates — embedded layout binaries and template definitions.

Pure data module with no TORCH imports. Provides template specifications
for standard building interiors (PokéCenter, PokéMart) including binary
layout data, NPC definitions, warp templates, and script templates.
"""
# TORCH_MODULE: Building Templates
# TORCH_GROUP: Data
import base64


# ============================================================
# Map metadata defaults (shared across all indoor templates)
# ============================================================
INDOOR_DEFAULTS = {
    "requires_flash": False,
    "weather": "WEATHER_NONE",
    "map_type": "MAP_TYPE_INDOOR",
    "allow_cycling": False,
    "allow_escaping": False,
    "allow_running": False,
    "show_map_name": False,
    "battle_scene": "MAP_BATTLE_SCENE_NORMAL",
    "connections": None,
    "coord_events": [],
    "bg_events": [],
}


# ============================================================
# Base64-encoded binary layout data (extracted from vanilla)
# ============================================================
_B64 = {
    "pokecenter_1f_map": "CAYJBmkGagYLBgsGCwZKBksGCwYMBg0GDgYPBhAGEQZxBnIGSAYiBiMGUgZTBkkGBAQVBhYGFwYYMhkyeTJ6MlAGKgYrBgcyWwZRBiQyHTIeMh8yIDImMjQyAjJYBiEGIQYFBiEGWQY8MgIyAjInMiAyAjICMgIyYDJsMm0ybjJvMgYyJTICMgIyJzKAMoEyAjICMgIyMDIxMjIyMzICMgIyAjICMicyiDaJQgICAjICMjgyOTI6MjsyAjI0Mj0GPgYnMpAykTICMgIyAjJAMkEyQjJDMgIyJjJFBkYGJzIoBgIyAjICMgIyAjIDMgQyAjICMgIyJjI0Mjc2",
    "pokecenter_1f_border": "AQIBAgECAQI=",
    "pokecenter_2f_map": "CAYLBgsGPwYLBlwGCwYLBj8GXAYLBgsGPwYPBhAGEwYTBkcGEwZkNhMGEwZHBmQ2EwYTBkcGFwbYAtkC2QKmBs8CHjLNAs8CTwYeMs0CzwJPBmIy1gbgBuAGBATXBl0G1QbXBtsGXQbVBtcG2gYvMiAybDJsMrYyYQICMr8ybDLjBjwCvzJsMuIGLzKYMpkyAjICMsoyyzLMMgIyZzLIMskyAjJnMkQCoAahQgICAjLSMtMy1DICMgIy0DLRMgIyAjInMqgyqTICMgIyAjICMgIyAjICMgIyAjICMgIyJzIgMgIyAjICMgIyXjJeMgIyAjJeMl4yAjICMicyKDYCMgIyNDICMmYGZgY0MiYyZgZmBiYyNDI3Ng==",
    "pokecenter_2f_border": "AQIBAgECAQI=",
    "pokemart_map": "EAYiBhIGEwYTBhMGIwYkBiMGJAYVBhgGRAYqBhsGGwYbBigGKQYoBikGHQYgMggyMgYLMggyCDIwMjEyITIxMiUyGAM5MjoGBjIBMgEyATIBMgEyATItBiAHQQZCBgYyATIBMisGLAYEMgEyKwYKMggyCDICMgEyATIzBjQGBjIBMjMGCjIBMgEyATIBMgEyOwY8BgYyATI7BhQyATIBMhYCFwIBMg8yCDICMgEyHDI=",
    "pokemart_border": "AQABAAEAAQA=",
}

# Decode all binaries at import time
_BIN = {k: base64.b64decode(v) for k, v in _B64.items()}


# ============================================================
# Template definitions
# ============================================================
TEMPLATES = {
    "pokecenter_1f": {
        "map_bin": _BIN["pokecenter_1f_map"],
        "border_bin": _BIN["pokecenter_1f_border"],
        "width": 14,
        "height": 9,
        "primary_tileset": "gTileset_Building",
        "secondary_tileset": "gTileset_PokemonCenter",
        "music": "MUS_POKE_CENTER",
        "map_type": "MAP_TYPE_INDOOR",
        "shared_layout_id": "LAYOUT_POKEMON_CENTER_1F",
        "shared_layout_name": "PokemonCenter_1F_Layout",
        "shared_layout_dir": "PokemonCenter_1F",
        "object_events": [
            {
                "graphics_id": "OBJ_EVENT_GFX_NURSE",
                "x": 7, "y": 2,
                "elevation": 3,
                "movement_type": "MOVEMENT_TYPE_FACE_DOWN",
                "movement_range_x": 0, "movement_range_y": 0,
                "trainer_type": "TRAINER_TYPE_NONE",
                "trainer_sight_or_berry_tree_id": "0",
                "script": "{map_name}_EventScript_Nurse",
                "flag": "0",
            },
        ],
        "warp_events": [
            {"x": 7, "y": 8, "elevation": 3, "dest_map": "{parent_map_const}", "dest_warp_id": "{parent_warp_id}"},
            {"x": 6, "y": 8, "elevation": 3, "dest_map": "{parent_map_const}", "dest_warp_id": "{parent_warp_id}"},
            {"x": 1, "y": 6, "elevation": 4, "dest_map": "{pc2f_map_const}", "dest_warp_id": "0", "conditional": "include_2f"},
        ],
        "script_template": (
            "mapscripts {map_name}_MapScripts {}\n"
            "\n"
            "script {map_name}_EventScript_Nurse {\n"
            "    lock\n"
            "    faceplayer\n"
            "    setvar(VAR_0x800B, 1)\n"
            "    call(Common_EventScript_PkmnCenterNurse)\n"
            "    waitmessage\n"
            "    waitbuttonpress\n"
            "    release\n"
            "    end\n"
            "}\n"
        ),
    },
    "pokecenter_2f": {
        "map_bin": _BIN["pokecenter_2f_map"],
        "border_bin": _BIN["pokecenter_2f_border"],
        "width": 14,
        "height": 10,
        "primary_tileset": "gTileset_Building",
        "secondary_tileset": "gTileset_PokemonCenter",
        "music": "MUS_POKE_CENTER",
        "map_type": "MAP_TYPE_INDOOR",
        "shared_layout_id": "LAYOUT_POKEMON_CENTER_2F",
        "shared_layout_name": "PokemonCenter_2F_Layout",
        "shared_layout_dir": "PokemonCenter_2F",
        "object_events": [
            {
                "graphics_id": "OBJ_EVENT_GFX_TEALA",
                "x": 2, "y": 2, "elevation": 3,
                "movement_type": "MOVEMENT_TYPE_FACE_DOWN",
                "movement_range_x": 0, "movement_range_y": 0,
                "trainer_type": "TRAINER_TYPE_NONE",
                "trainer_sight_or_berry_tree_id": "0",
                "script": "Common_EventScript_WirelessClubAttendant",
                "flag": "0",
            },
            {
                "graphics_id": "OBJ_EVENT_GFX_TEALA",
                "x": 6, "y": 2, "elevation": 0,
                "movement_type": "MOVEMENT_TYPE_FACE_DOWN",
                "movement_range_x": 0, "movement_range_y": 0,
                "trainer_type": "TRAINER_TYPE_NONE",
                "trainer_sight_or_berry_tree_id": "0",
                "script": "Common_EventScript_UnionRoomAttendant",
                "flag": "0",
            },
            {
                "graphics_id": "OBJ_EVENT_GFX_TEALA",
                "x": 10, "y": 2, "elevation": 0,
                "movement_type": "MOVEMENT_TYPE_FACE_DOWN",
                "movement_range_x": 0, "movement_range_y": 0,
                "trainer_type": "TRAINER_TYPE_NONE",
                "trainer_sight_or_berry_tree_id": "0",
                "script": "Common_EventScript_DirectCornerAttendant",
                "flag": "0",
            },
        ],
        "warp_events": [
            {"x": 1, "y": 6, "elevation": 4, "dest_map": "{pc1f_map_const}", "dest_warp_id": "2"},
            {"x": 5, "y": 1, "elevation": 3, "dest_map": "MAP_UNION_ROOM", "dest_warp_id": "0"},
            {"x": 9, "y": 1, "elevation": 3, "dest_map": "MAP_TRADE_CENTER", "dest_warp_id": "0"},
        ],
        "script_template": "mapscripts {map_name}_MapScripts {}\n",
    },
    "pokemart": {
        "map_bin": _BIN["pokemart_map"],
        "border_bin": _BIN["pokemart_border"],
        "width": 11,
        "height": 8,
        "primary_tileset": "gTileset_Building",
        "secondary_tileset": "gTileset_Shop",
        "music": "MUS_POKE_MART",
        "map_type": "MAP_TYPE_INDOOR",
        "shared_layout_id": "LAYOUT_MART",
        "shared_layout_name": "Mart_Layout",
        "shared_layout_dir": "Mart",
        "object_events": [
            {
                "graphics_id": "OBJ_EVENT_GFX_MART_EMPLOYEE",
                "x": 1, "y": 3, "elevation": 3,
                "movement_type": "MOVEMENT_TYPE_FACE_RIGHT",
                "movement_range_x": 0, "movement_range_y": 0,
                "trainer_type": "TRAINER_TYPE_NONE",
                "trainer_sight_or_berry_tree_id": "0",
                "script": "{map_name}_EventScript_Clerk",
                "flag": "0",
            },
        ],
        "warp_events": [
            {"x": 3, "y": 7, "elevation": 0, "dest_map": "{parent_map_const}", "dest_warp_id": "{parent_warp_id}"},
            {"x": 4, "y": 7, "elevation": 0, "dest_map": "{parent_map_const}", "dest_warp_id": "{parent_warp_id}"},
        ],
        "script_template": (
            "mapscripts {map_name}_MapScripts {}\n"
            "\n"
            "script {map_name}_EventScript_Clerk {\n"
            "    lock\n"
            "    faceplayer\n"
            "    msgbox({map_name}_Text_Greeting, MSGBOX_DEFAULT)\n"
            "    pokemart({map_name}_MartItems)\n"
            "    msgbox({map_name}_Text_Goodbye, MSGBOX_DEFAULT)\n"
            "    release\n"
            "    end\n"
            "}\n"
            "\n"
            "text {map_name}_Text_Greeting {\n"
            '    "Welcome!\\p"\n'
            '    "How may I serve you?$"\n'
            "}\n"
            "\n"
            "text {map_name}_Text_Goodbye {\n"
            '    "Please come again!$"\n'
            "}\n"
            "\n"
            "raw `\n"
            "\t.align 2\n"
            "{map_name}_MartItems:\n"
            "\t.2byte ITEM_POKE_BALL\n"
            "\t.2byte ITEM_POTION\n"
            "\t.2byte ITEM_ANTIDOTE\n"
            "\t.2byte ITEM_PARALYZE_HEAL\n"
            "\t.2byte ITEM_AWAKENING\n"
            "\t.2byte ITEM_NONE\n"
            "\trelease\n"
            "\tend\n"
            "`\n"
        ),
    },
}
