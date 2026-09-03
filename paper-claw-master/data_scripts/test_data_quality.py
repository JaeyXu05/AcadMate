"""RAG 清洗/证据口径的纯 stdlib 回归测试。"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("build_rag.py")
SPEC = importlib.util.spec_from_file_location("build_rag_under_test", MODULE_PATH)
assert SPEC and SPEC.loader
build_rag = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_rag)


class DataQualityTests(unittest.TestCase):
    def test_topic_cleaner_preserves_scientific_navigation(self) -> None:
        self.assertEqual(build_rag._clean_profile_topic("导航与制导"), "导航与制导")
        self.assertEqual(
            build_rag._clean_profile_topic("机器人视觉：无人自主小车的视觉导航"),
            "机器人视觉：无人自主小车的视觉导航",
        )

    def test_topic_cleaner_drops_proven_template_noise(self) -> None:
        for value in ("总访问量", "教学信息", "新闻动态", "KTX实验室"):
            with self.subTest(value=value):
                self.assertIsNone(build_rag._clean_profile_topic(value))
        for value in (
            "欢迎点赞",
            "Honors & Awards",
            "Social Affiliations",
            "an adjunct professor of UMass Amherst from 2016 to 2019",
            "京东探索研究院优秀实习生",
            "IEEE Trans. on CSVT",
            "已在IEEE Trans. Signal Processing",
            "ICIP 2024",
            "03-15",
        ):
            with self.subTest(value=value):
                self.assertIsNone(build_rag._clean_profile_topic(value))
        for value in (
            "“Upgrading glycerol to sorbose via a tandem photoelectrocatalysis-enzyme catalysis relay”",
            "An X-ray model of amorphous materials. Ultramicroscopy 23, 88-94 (2018)",
            "An X-ray model of amorphous materials. Ultramicroscopy 23",
        ):
            with self.subTest(value=value):
                self.assertIsNone(build_rag._clean_profile_topic(value))

    def test_ambiguous_single_words_do_not_backfill_topics(self) -> None:
        titles = ["Carbon cell material control under optical observation"]
        self.assertEqual(build_rag._paper_topics_from_titles(titles), [])

    def test_cross_platform_dedupe_prefers_doi_then_title(self) -> None:
        papers = [
            {"title": "A Study", "doi": "10.1000/ABC", "openalex_id": "W1"},
            {"title": "A study.", "doi": "https://doi.org/10.1000/abc", "s2_paper_id": "S1"},
            {"title": "A   Study", "dblp_key": "D1"},
        ]
        self.assertEqual(len(build_rag._dedupe_papers(papers)), 1)

    def test_profile_role_requires_strong_context(self) -> None:
        self.assertIsNone(build_rag._profile_mentor_role("张三", "P同专业博导 M同专业硕导"))
        self.assertEqual(
            build_rag._profile_mentor_role("张三", "张三，中国科学技术大学教授、博士生导师。"),
            "博士生导师",
        )
        self.assertEqual(
            build_rag._profile_mentor_role("张三", "个人简介\n博士生导师，中国科学技术大学教授。"),
            "博士生导师",
        )
        self.assertEqual(
            build_rag._profile_mentor_role("张三", "仪器科学与技术学科点硕导"),
            "硕导",
        )


if __name__ == "__main__":
    unittest.main()
