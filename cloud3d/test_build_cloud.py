import json
import math
import random
import tempfile
import unittest
from pathlib import Path

from build_cloud import build, domain_scores, double_orbit_domain_center


class DomainScoringTests(unittest.TestCase):
    def test_scores_are_sorted_by_keyword_evidence(self):
        scores = domain_scores(["量子计算 深度学习 机器学习 神经网络 图神经网络"])
        self.assertEqual(scores[0][0]["id"], "cs_ai")
        self.assertGreater(scores[0][1], scores[1][1])

    def test_unknown_text_does_not_get_a_fake_domain(self):
        self.assertEqual(domain_scores(["完全没有领域关键词的资料"]), [])

    def test_domain_centers_use_two_even_but_not_mechanical_orbits(self):
        outer = [double_orbit_domain_center(index, 6, 390, 0, f"outer-{index}") for index in range(6)]
        inner = [double_orbit_domain_center(index, 5, 245, math.pi / 5, f"inner-{index}") for index in range(5)]
        outer_radii = [math.hypot(x, z) for x, z, _ in outer]
        inner_radii = [math.hypot(x, z) for x, z, _ in inner]
        self.assertTrue(all(383 <= radius <= 397 for radius in outer_radii))
        self.assertTrue(all(238 <= radius <= 252 for radius in inner_radii))
        self.assertGreater(max(outer_radii) - min(outer_radii), 1)
        self.assertGreater(max(inner_radii) - min(inner_radii), 1)
        for centers in (outer, inner):
            angles = sorted((angle % (2 * math.pi)) for _, _, angle in centers)
            gaps = [(angles[(index + 1) % len(angles)] - angles[index]) % (2 * math.pi) for index in range(len(angles))]
            expected = 2 * math.pi / len(angles)
            self.assertTrue(all(abs(gap - expected) < 0.06 for gap in gaps))


class CloudBuildContractTests(unittest.TestCase):
    def test_build_preserves_ids_and_marks_unclassified_nodes(self):
        rag = {
            "generated_at": "2026-08-24T00:00:00+08:00",
            "source_chain": ["internal_ustc_rag"],
            "evidence_count": 2,
            "candidates": [
                {
                    "candidate_id": "ustc_faculty_1",
                    "mentor_name": "甲",
                    "department": "计算机科学与技术学院",
                    "research_topics": ["机器学习", "深度学习"],
                    "publications": ["Paper A"],
                },
                {
                    "candidate_id": "ustc_faculty_2",
                    "mentor_name": "乙",
                    "department": "未提供",
                    "research_topics": [],
                    "publications": [],
                },
            ],
        }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rag_path = root / "rag.json"
            output_path = root / "cloud.json"
            rag_path.write_text(json.dumps(rag, ensure_ascii=False), encoding="utf-8")
            random.seed(42)
            result = build(str(rag_path), str(output_path))

        self.assertEqual(result["meta"]["schema_version"], 2)
        self.assertEqual(result["meta"]["mentor_count"], len(rag["candidates"]))
        self.assertEqual({node["candidate_id"] for node in result["nodes"]}, {"ustc_faculty_1", "ustc_faculty_2"})
        unknown = next(node for node in result["nodes"] if node["candidate_id"] == "ustc_faculty_2")
        self.assertEqual(unknown["domain"], "unclassified")
        self.assertEqual(unknown["classification_status"], "unclassified")
        self.assertTrue(all(math.isfinite(node[axis]) for node in result["nodes"] for axis in ("x", "y", "z")))

    def test_checked_in_cloud_matches_current_local_rag(self):
        root = Path(__file__).resolve().parents[1]
        rag_path = root / "paper-claw-master" / "data" / "ustc_mentor_rag.json"
        cloud_path = root / "cloud3d" / "cloud_data.json"
        if not rag_path.exists():
            self.skipTest("本地 RAG 数据未安装")

        rag = json.loads(rag_path.read_text(encoding="utf-8"))
        cloud = json.loads(cloud_path.read_text(encoding="utf-8"))
        rag_ids = {candidate["candidate_id"] for candidate in rag["candidates"]}
        cloud_ids = {node["candidate_id"] for node in cloud["nodes"]}

        self.assertEqual(cloud_ids, rag_ids)
        self.assertEqual(cloud["meta"]["mentor_count"], len(rag_ids))
        self.assertEqual(cloud["meta"]["evidence_count"], len(rag["evidence"]))
        self.assertEqual(sum(item["count"] for item in cloud["meta"]["legend"]), len(rag_ids))
        self.assertTrue(all(math.isfinite(node[axis]) for node in cloud["nodes"] for axis in ("x", "y", "z")))


if __name__ == "__main__":
    unittest.main()
