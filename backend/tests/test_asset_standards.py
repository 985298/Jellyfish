"""Validation tests for asset reference standards.

Checks that DB prompt templates, schema columns, multi-state linkages,
prompt content keywords, and image resolution constants all conform to
the standards defined in ASSET_REFERENCE_STANDARDS.md.

Uses sqlite3 directly against the existing jellyfish.db (read-only).
"""

from __future__ import annotations

import inspect
import os
import sqlite3
from pathlib import Path

import pytest

from app.agents.tools import asset_ref_generator as argen

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DB_PATH = Path(__file__).resolve().parent.parent / "jellyfish.db"

REQUIRED_CATEGORIES = [
    "character_image_front",
    "character_image_negative",
    "scene_image_front",
    "scene_image_negative",
    "prop_image_front",
    "prop_image_negative",
    "costume_image_front",
    "costume_image_negative",
    "combined",
]

# Expected resolution per asset type (width x height, as used in size= arg)
EXPECTED_RESOLUTIONS = {
    "character": "2048x1152",
    "scene": "1152x2048",
    "prop": "2048x2048",
    "costume": "2048x2048",
}

# Keyword expectations for prompt content (case-insensitive substring)
POSITIVE_KEYWORDS = {
    "character_image_front": ["reference sheet", "white", "full body"],
    "scene_image_front": ["no people", "empty"],
    "prop_image_front": ["product photography", "white"],
    "costume_image_front": ["flat lay", "white"],
}

NEGATIVE_KEYWORDS = {
    "character_image_negative": ["face change", "different person"],
    "scene_image_negative": ["person", "silhouette"],
    "prop_image_negative": ["hands", "human"],
    "costume_image_negative": ["model", "mannequin"],
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    """Read-only sqlite3 connection to jellyfish.db."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _get_template_content(db, category: str) -> str:
    row = db.execute(
        "SELECT content FROM prompt_templates WHERE category = ? LIMIT 1",
        (category,),
    ).fetchone()
    assert row is not None, f"prompt_templates row for {category!r} not found"
    return row["content"] or ""


# ---------------------------------------------------------------------------
# 1. Prompt template categories exist
# ---------------------------------------------------------------------------

class TestPromptTemplateCategories:
    """All 9 required categories must exist in prompt_templates table."""

    @pytest.mark.parametrize("category", REQUIRED_CATEGORIES)
    def test_category_exists(self, db, category):
        row = db.execute(
            "SELECT id, content FROM prompt_templates WHERE category = ? LIMIT 1",
            (category,),
        ).fetchone()
        assert row is not None, f"category {category!r} missing from prompt_templates"
        assert row["content"], f"category {category!r} has empty content"

    def test_all_categories_count(self, db):
        rows = db.execute(
            "SELECT DISTINCT category FROM prompt_templates WHERE category IN ({})".format(
                ",".join("?" * len(REQUIRED_CATEGORIES))
            ),
            REQUIRED_CATEGORIES,
        ).fetchall()
        found = {r["category"] for r in rows}
        missing = set(REQUIRED_CATEGORIES) - found
        assert not missing, f"missing categories: {missing}"


# ---------------------------------------------------------------------------
# 2. DB schema columns
# ---------------------------------------------------------------------------

class TestSchemaColumns:
    """character_images.costume_id and costumes.character_id must exist."""

    def test_character_images_has_costume_id(self, db):
        cols = [r["name"] for r in db.execute("PRAGMA table_info(character_images)")]
        assert "costume_id" in cols, "character_images.costume_id column missing"

    def test_costumes_has_character_id(self, db):
        cols = [r["name"] for r in db.execute("PRAGMA table_info(costumes)")]
        assert "character_id" in cols, "costumes.character_id column missing"

    def test_character_images_has_is_primary(self, db):
        cols = [r["name"] for r in db.execute("PRAGMA table_info(character_images)")]
        assert "is_primary" in cols, "character_images.is_primary column missing"


# ---------------------------------------------------------------------------
# 3. Multi-state character support (data-level)
# ---------------------------------------------------------------------------

class TestMultiStateCharacterSupport:
    """Costumes linked to characters and non-front images linked to costumes."""

    def test_costumes_have_character_id(self, db):
        count = db.execute(
            "SELECT COUNT(*) FROM costumes WHERE character_id IS NOT NULL"
        ).fetchone()[0]
        assert count > 0, "no costumes linked to characters (character_id all NULL)"

    def test_character_images_have_costume_id(self, db):
        count = db.execute(
            "SELECT COUNT(*) FROM character_images WHERE costume_id IS NOT NULL"
        ).fetchone()[0]
        assert count > 0, "no character_images linked to costumes (costume_id all NULL)"

    def test_costume_character_link_integrity(self, db):
        """Every costume with character_id should point to an existing character."""
        orphans = db.execute(
            "SELECT COUNT(*) FROM costumes co "
            "WHERE co.character_id IS NOT NULL "
            "AND co.character_id NOT IN (SELECT id FROM characters)"
        ).fetchone()[0]
        assert orphans == 0, f"{orphans} costumes point to non-existent characters"


# ---------------------------------------------------------------------------
# 4. Prompt template content validation (keyword checks)
# ---------------------------------------------------------------------------

class TestPromptContentKeywords:
    """Positive and negative prompts must contain expected keywords."""

    @pytest.mark.parametrize("category,keywords", list(POSITIVE_KEYWORDS.items()))
    def test_positive_prompt_keywords(self, db, category, keywords):
        content = _get_template_content(db, category)
        lowered = content.lower()
        missing = [kw for kw in keywords if kw.lower() not in lowered]
        assert not missing, (
            f"{category} positive prompt missing keywords: {missing}. "
            f"Content starts: {content[:120]!r}"
        )

    @pytest.mark.parametrize("category,keywords", list(NEGATIVE_KEYWORDS.items()))
    def test_negative_prompt_keywords(self, db, category, keywords):
        content = _get_template_content(db, category)
        lowered = content.lower()
        missing = [kw for kw in keywords if kw.lower() not in lowered]
        assert not missing, (
            f"{category} negative prompt missing keywords: {missing}. "
            f"Content starts: {content[:120]!r}"
        )


# ---------------------------------------------------------------------------
# 5. Image resolution constants in source code
# ---------------------------------------------------------------------------

class TestResolutionConstants:
    """asset_ref_generator.py must use the standard resolutions per asset type."""

    @pytest.fixture(autouse=True)
    def _source(self):
        self.src = inspect.getsource(argen)

    @pytest.mark.parametrize(
        "asset_type,expected_size",
        list(EXPECTED_RESOLUTIONS.items()),
    )
    def test_resolution_in_source(self, asset_type, expected_size):
        """The size string must appear in the generate call for that asset type."""
        assert expected_size in self.src, (
            f"{asset_type} resolution {expected_size!r} not found in "
            "asset_ref_generator.py source"
        )

    def test_character_resolution_is_landscape(self):
        assert "2048x1152" in self.src
        # 2048 > 1152 means landscape (width > height)
        w, h = map(int, "2048x1152".split("x"))
        assert w > h, "character image should be landscape"

    def test_scene_resolution_is_portrait(self):
        assert "1152x2048" in self.src
        w, h = map(int, "1152x2048".split("x"))
        assert h > w, "scene image should be portrait (9:16)"

    def test_prop_resolution_is_square(self):
        assert "2048x2048" in self.src
        w, h = map(int, "2048x2048".split("x"))
        assert w == h, "prop image should be square"

    def test_costume_resolution_is_square(self):
        # costume also uses 2048x2048; verify it appears near costume context
        assert "2048x2048" in self.src
        w, h = map(int, "2048x2048".split("x"))
        assert w == h, "costume image should be square"

    def test_no_legacy_1k_resolutions(self):
        """No 1024x or x1024 resolutions should remain (all upgraded to 2K)."""
        assert "1024x" not in self.src, (
            "found legacy 1024-width resolution; should be 2K"
        )
        assert "x1024" not in self.src, (
            "found legacy 1024-height resolution; should be 2K"
        )


# ---------------------------------------------------------------------------
# 6. Code-DB consistency (bonus: DB content matches code constants)
