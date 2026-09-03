import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).parents[3] / "data_scripts" / "internal_mentor_rag.py"
SPEC = importlib.util.spec_from_file_location("internal_mentor_rag_under_test", MODULE_PATH)
assert SPEC and SPEC.loader
internal_rag = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(internal_rag)

_cosine_similarity = internal_rag._cosine_similarity
_high_coverage_cjk_match = internal_rag._high_coverage_cjk_match


def test_cosine_uses_both_vector_weights():
    # With a single overlapping feature, cosine should be 1 regardless of its
    # absolute weight.  The former one-sided dot product returned 0.5 here.
    assert _cosine_similarity({"specific": 2.0}, {"specific": 1.0}) == 1.0


def test_cjk_recall_allows_high_coverage_label_variant_only():
    assert _high_coverage_cjk_match(["微分方程"], "常微分方程")
    assert not _high_coverage_cjk_match(["随机图"], "随机过程")
