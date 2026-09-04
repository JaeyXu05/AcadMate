from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from data_scripts.build_rag import (
    _keyword_in_title,
    _paper_identity_status,
    _paper_topics_from_titles,
)


def test_short_ascii_keyword_uses_real_word_boundaries():
    assert _keyword_in_title("soc", "Low-power SoC architecture")
    assert not _keyword_in_title("soc", "Social network analysis")
    assert not _keyword_in_title("soc", "Society-scale recommender systems")


def test_generic_paper_topic_requires_repeated_support():
    assert "碳材料" not in _paper_topics_from_titles(["Carbon flux in an unrelated case study"])
    assert "碳材料" in _paper_topics_from_titles([
        "Carbon materials for energy storage",
        "Porous carbon materials with high stability",
    ])


def test_exact_name_match_is_still_pending_without_entity_verification():
    source = {"s2_author_id": "123", "s2_exact_match": True}
    status, _ = _paper_identity_status("1", source, {})
    assert status == "pending"


def test_manual_author_id_verifies_or_rejects_selected_entity():
    source = {"s2_author_id": "123", "s2_exact_match": True}
    assert _paper_identity_status("1", source, {"1": {"Semantic Scholar": "123"}})[0] == "verified"
    assert _paper_identity_status("1", source, {"1": {"Semantic Scholar": "456"}})[0] == "rejected"
