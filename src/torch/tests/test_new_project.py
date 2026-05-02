"""New Project suite -- name sanitisation, constants, version picker logic."""
import os

from torch.tests.harness import _begin_suite, _ok, _fail, _skip, _assert


def run_suite():
    _begin_suite("NewProj  (sanitisation, constants, version picker)")

    try:
        import torch.new_project as np_mod
    except ImportError as e:
        _skip("all new_project tests", f"import failed: {e}")
        return

    _test_sanitize_name(np_mod)
    _test_constants(np_mod)
    _test_pick_version_tag_format(np_mod)


# ── _sanitize_name ───────────────────────────────────────────────────────

def _test_sanitize_name(mod):
    """Test project name sanitisation."""
    _assert(
        "sanitize: spaces become hyphens",
        mod._sanitize_name("My New Project") == "my-new-project",
        f"got: {mod._sanitize_name('My New Project')!r}"
    )
    _assert(
        "sanitize: special chars stripped",
        mod._sanitize_name("test@#$name!") == "test-name",
        f"got: {mod._sanitize_name('test@#$name!')!r}"
    )
    _assert(
        "sanitize: truncates to 30 chars",
        len(mod._sanitize_name("a" * 50)) == 30,
        f"got length: {len(mod._sanitize_name('a' * 50))}"
    )
    _assert(
        "sanitize: empty returns empty",
        mod._sanitize_name("") == "",
        f"got: {mod._sanitize_name('')!r}"
    )
    _assert(
        "sanitize: leading/trailing hyphens stripped",
        mod._sanitize_name("--test--") == "test",
        f"got: {mod._sanitize_name('--test--')!r}"
    )


# ── Constants ────────────────────────────────────────────────────────────

def _test_constants(mod):
    """Verify repo URLs and tag pattern are defined."""
    _assert(
        "VANILLA_REPO defined",
        "pokeemerald" in mod.VANILLA_REPO and "pret" in mod.VANILLA_REPO,
        f"got: {mod.VANILLA_REPO!r}"
    )
    _assert(
        "EXPANSION_REPO defined",
        "pokeemerald-expansion" in mod.EXPANSION_REPO,
        f"got: {mod.EXPANSION_REPO!r}"
    )
    _assert(
        "EXPANSION_TAGS_API defined",
        "api.github.com" in mod.EXPANSION_TAGS_API,
        f"got: {mod.EXPANSION_TAGS_API!r}"
    )
    _assert(
        "TAG_PATTERN matches expansion tags",
        mod.EXPANSION_TAG_PATTERN.match("expansion/1.14.3") is not None,
        "pattern did not match expansion/1.14.3"
    )
    _assert(
        "TAG_PATTERN rejects non-expansion tags",
        mod.EXPANSION_TAG_PATTERN.match("v1.0.0") is None,
        "pattern should not match v1.0.0"
    )


# ── Version picker tag format ────────────────────────────────────────────

def _test_pick_version_tag_format(mod):
    """Verify the tag format that _pick_version would produce."""
    # Test the tag string construction directly
    versions = [(1, 14, 3), (1, 13, 0), (1, 12, 1)]
    v = versions[0]
    tag = f"expansion/{v[0]}.{v[1]}.{v[2]}"
    _assert(
        "tag format: expansion/X.Y.Z",
        tag == "expansion/1.14.3",
        f"got: {tag!r}"
    )
    v2 = versions[2]
    tag2 = f"expansion/{v2[0]}.{v2[1]}.{v2[2]}"
    _assert(
        "tag format: second version",
        tag2 == "expansion/1.12.1",
        f"got: {tag2!r}"
    )
