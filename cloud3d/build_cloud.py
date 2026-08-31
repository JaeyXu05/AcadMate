#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_cloud.py — 导师 3D 星图数据生成脚本（纯 Python 标准库，无第三方依赖）

每次运行时重新读取最新 RAG 数据库 data/ustc_mentor_rag.json，
计算每个导师的研究领域得分 / 银河盘 3D 坐标 / 学院映射 / 领域配色，
输出前端可直接加载的 cloud_data.json。

数据分离：
  build_cloud.py  (生成)  -->>  cloud_data.json  <!-- index.html (展示, Three.js)
正式前端可复用同一份 cloud_data.json，接口稳定。

用法:  py build_cloud.py  [--rag PATH] [--out PATH]
默认读取 ../paper-claw-master/data/ustc_mentor_rag.json，输出 ./cloud_data.json
不修改 data/ 下任何现有文件。
"""

import json
import math
import random
import sys
import os
from collections import defaultdict

# ---------------------------------------------------------------- 领域定义
# 每个宏观研究领域：关键词表(中/英，子串匹配) + 主色。
# 用于把当前 RAG 候选粗分为约 10 个研究版图。关键词覆盖 department / topics / methods。
DOMAINS = [
    {
        "id": "physics_quantum", "name": "物理·量子",
        "color": "#8a7bff",
        "keys": ["物理", "量子", "凝聚态", "光", "原子", "分子物理", "粒子",
                 "physics", "quantum", "condensed", "optical", "photon", "atomic",
                 "superconduct", "cavity", "semiconductor", "laser"],
    },
    {
        "id": "chemistry_materials", "name": "化学·材料",
        "color": "#56d4ae",
        "keys": ["化学", "材料", "催化", "纳米", "高分子", "催化", "电池", "聚合物",
                 "电化学", "有机", "无机", "chemistry", "material", "catalyst",
                 "polymer", "nanoparticle", "electrochem"],
    },
    {
        "id": "geo_space", "name": "地球·空间",
        "color": "#56c4f8",
        "keys": ["地球", "空间", "大气", "海洋", "地质", "地震", "行星", "环境",
                 "遥感", "冰川", "火山", "geophys", "atmos", "ocean", "seismic",
                 "planet", "geology", "remote sensing"],
    },
    {
        "id": "engineering", "name": "工程·力学",
        "color": "#ffd54a",
        "keys": ["工程", "力学", "机械", "流体", "结构", "材料力学", "制造",
                 "能源", "燃烧", "robot", "mechanical", "fluid", "structure",
                 "thermal", "combustion", "aerospace", "solid mechanics"],
    },
    {
        "id": "info_electronics", "name": "信息·电子",
        "color": "#ff8ba8",
        "keys": ["信息", "电子", "通信", "微电子", "集成电路", "信号", "网络",
                 "雷达", "光学工程", "电子", "circuit", "signal", "communication",
                 "viberation", "network", "RF", "mmwave"],
    },
    {
        "id": "cs_ai", "name": "计算机·人工智能",
        "color": "#74b3ff",
        "keys": ["计算机", "人工智能", "机器学习", "深度学习", "算法", "数据",
                 "软件", "网络空间", "安全", "大模型", "自然语言", "机器人",
                 "computer", "machine learning", "deep learning", "AI",
                 "algorithm", "software", "neural", "NLP", "vision"],
    },
    {
        "id": "bio_medicine", "name": "生命·医学",
        "color": "#ff8fd4",
        "keys": ["生命", "医学", "生物", "细胞", "基因", "免疫", "神经", "药",
                 "微生物", "生态", "biology", "medicine", "gene", "cell",
                 "immune", "oncology", "pharma", "genomics"],
    },
    {
        "id": "math", "name": "数学",
        "color": "#b7e35e",
        "keys": ["数学", "几何", "代数", "拓扑", "概率", "统计", "数论", "方程",
                 "math", "geometry", "algebra", "topology", "analysis",
                 "probability", "statistics"],
    },
    {
        "id": "energy_env", "name": "能源·环境",
        "color": "#5fd9b4",
        "keys": ["能源", "环境", "核", "辐射", "同步辐射", "聚变", "等离子体",
                 "燃料电池", "储能", "eco", "energy", "nuclear", "fusion",
                 "plasma", "radiation", "environment", "solar", "renewable"],
    },
    {
        "id": "manage_humanities", "name": "管理·人文",
        "color": "#d6a0ff",
        "keys": ["管理", "经济", "人文", "社会", "传播", "法律", "哲学", "心理",
                 "management", "econom", "sociology", "finance", "humanities",
                 "business", "psychology"],
    },
]

# 真实资料不足时保持“未知”，不能为了填满图例而伪装成某个学科。
UNKNOWN_DOMAIN = {
    "id": "unclassified",
    "name": "待分类",
    "color": "#a7b0c0",
    "keys": [],
}


def domain_scores(text_blocks):
    """返回 [(domain, score)]，按得分降序。score = 命中关键词总数(去重)。"""
    text = " ".join(t or "" for t in text_blocks).lower()
    scored = []
    for d in DOMAINS:
        n = sum(1 for k in d["keys"] if k.lower() in text)
        if n > 0:
            scored.append((d, n))
    # 同分时保留 DOMAINS 的稳定声明顺序；主领域必须由命中分而非声明先后决定。
    scored.sort(key=lambda item: -item[1])
    return scored


# ---------------------------------------------------------------- 球面布局
def fibonacci_sphere(n, radius=1.0):
    """在球面上生成 n 个近似均匀分布的点 (x,y,z)。"""
    pts = []
    ga = math.pi * (3 - math.sqrt(5))  # golden angle
    for i in range(n):
        y = 1 - (i / max(1, n - 1)) * 2
        r = math.sqrt(1 - y * y)
        th = ga * i
        pts.append((math.cos(th) * r * radius, y * radius, math.sin(th) * r * radius))
    return pts


def double_orbit_domain_center(slot, total, radius, phase, jitter_key):
    """双轨质心：等距为主，只加入有界的确定性角度/半径误差。"""
    seed = sum((index + 1) * ord(char) for index, char in enumerate(jitter_key))
    angular_jitter = ((((seed * 37) % 997) / 996.0) - 0.5) * 0.05  # ±0.025 rad
    radial_jitter = ((((seed * 71 + 17) % 991) / 990.0) - 0.5) * 14.0  # ±7 units
    angle = -math.pi / 2 + phase + slot * 2 * math.pi / max(1, total) + angular_jitter
    actual_radius = radius + radial_jitter
    return actual_radius * math.cos(angle), actual_radius * math.sin(angle), angle


def halo_points(base_theta, base_phi, radius, count, spread=0.5):
    """在球面上某点附近散布 count 个点（bumpy sphere 局部集群）。"""
    out = []
    for _ in range(count):
        r = radius * (0.94 + random.random() * 0.12)      # 径向抖动制造云层厚实感
        dtheta = (random.random() - 0.5) * spread
        dphi = (random.random() - 0.5) * spread * (1.0 / max(0.2, math.cos(base_phi) if abs(math.cos(base_phi)) > 0.2 else 0.2) ** 0.5)
        th = base_theta + dtheta
        ph = base_phi + dphi
        x = r * math.cos(ph) * math.cos(th)
        y = r * math.sin(ph)
        z = r * math.cos(ph) * math.sin(th)
        out.append((x, y, z))
    return out


# ---------------------------------------------------------------- 主逻辑
def build(rag_path, out_path):
    with open(rag_path, encoding="utf-8") as f:
        rag = json.load(f)

    cands = rag["candidates"]

    # 1) 给每位导师算领域得分，定主领域
    scored = []
    for c in cands:
        blocks = [c.get("department"), " ".join(c.get("research_topics") or []),
                  " ".join(c.get("methods") or [])]
        s = domain_scores(blocks)
        if not s:
            # 兜底：按学院名再试（部分 department 本身就是关键词），再无则给默认
            s = domain_scores([c.get("department") or ""])
        primary = s[0][0] if s else UNKNOWN_DOMAIN
        # 次领域（用于微调方向）
        secondary = s[1][0] if len(s) > 1 else None
        scored.append((c, primary, secondary, s))

    # 2) 领域质心分布在错位双轨，导师在各自领域内使用向日葵盘均匀铺开。
    #    领域仍由真实 RAG 分类决定；只调整视觉坐标，不改变节点、字段或关系语义。
    by_domain = defaultdict(list)
    for c, primary, secondary, s in scored:
        by_domain[primary["id"]].append((c, primary, secondary, s))
    N_ARMS = 4            # 仅描述背景银河的四条旋臂
    R_IN = 120.0
    R_OUT = 570.0
    N_dom = len(by_domain)
    ranked_domains = sorted(by_domain.items(), key=lambda item: (-len(item[1]), item[0]))
    # 大领域放外轨获得更多周向空间，小领域放内轨；内轨相对外轨旋转半个槽位。
    outer_count = (N_dom + 1) // 2
    outer_domains = ranked_domains[:outer_count]
    inner_domains = ranked_domains[outer_count:]
    orbit_plan = {}
    for slot, (dom_id, _) in enumerate(outer_domains):
        orbit_plan[dom_id] = (slot, len(outer_domains), 390.0, 0.0)
    inner_phase = math.pi / max(1, len(inner_domains))
    for slot, (dom_id, _) in enumerate(inner_domains):
        orbit_plan[dom_id] = (slot, len(inner_domains), 245.0, inner_phase)
    GOLDEN_ANGLE = math.pi * (3 - math.sqrt(5))

    # 3) 生成导师坐标：质心等距，簇内点使用确定性的低差异序列，密度平滑且无随机空洞。
    nodes = []
    for dom_id, members in sorted(by_domain.items()):
        count = len(members)
        slot, ring_count, orbit_radius, phase_offset = orbit_plan[dom_id]
        cx_, cz_, center_angle = double_orbit_domain_center(
            slot, ring_count, orbit_radius, phase_offset, dom_id
        )
        cluster_radius = min(96.0, 24.0 + 6.0 * math.sqrt(count))
        ordered_members = sorted(members, key=lambda item: item[0]["candidate_id"])
        phase = center_angle * 0.47 + slot * 0.19
        for index, (c, primary, secondary, s) in enumerate(ordered_members):
            local_radius = cluster_radius * math.sqrt((index + 0.55) / max(1, count))
            local_angle = phase + index * GOLDEN_ANGLE
            # 小幅确定性波动打破机械圆盘边界，但不重新制造随机热点。
            ripple = 1.0 + 0.045 * math.sin(index * 1.71 + slot)
            px = cx_ + local_radius * ripple * math.cos(local_angle)
            pz = cz_ + local_radius * ripple * math.sin(local_angle)
            r = math.hypot(px, pz)
            py = 13.0 * math.sin(index * 2.17 + slot * 0.73) + 4.0 * math.sin(index * 0.61)
            r_norm0 = max(0.0, min(1.0, (r - R_IN) / (R_OUT - R_IN)))
            core_lum = round((1.0 - r_norm0) ** 1.35, 3)
            nodes.append({
                "candidate_id": c["candidate_id"],
                "name": c.get("mentor_name") or "",
                "department": c.get("department") or "",
                "affiliation": c.get("affiliation") or "",
                "domain": primary["id"],
                "domain_name": primary["name"],
                "secondary": secondary["name"] if secondary else None,
                "classification_status": "classified" if s else "unclassified",
                "classification_score": s[0][1] if s else 0,
                "classification_margin": (s[0][1] - s[1][1]) if len(s) > 1 else (s[0][1] if s else 0),
                "color": primary["color"],
                "lum": round(luminance(c, primary), 3),
                "core_lum": core_lum,
                "size": star_size(c),
                "x": round(px, 4), "y": round(py, 4), "z": round(pz, 4),
                "topics": (c.get("research_topics") or [])[:6],
                "methods": (c.get("methods") or [])[:6],
                "pub_count": len(c.get("publications") or []),
                "pubs": (c.get("publications") or [])[:5],
                "homepage": c.get("homepage") or "",
                "recruitment": c.get("recruitment_status") or "",
            })

    # 4) 图例 = 领域列表（按人口排序）
    dom_counts = defaultdict(int)
    for n in nodes:
        dom_counts[n["domain"]] += 1
    legend_domains = [*DOMAINS, UNKNOWN_DOMAIN]
    legend = [{"id": d["id"], "name": d["name"], "color": d["color"],
               "count": dom_counts.get(d["id"], 0)}
              for d in legend_domains if dom_counts.get(d["id"], 0) > 0]
    legend.sort(key=lambda x: -x["count"])

    # 5) 顶层元信息 + 统计
    meta = {
        "schema_version": 2,
        "title": "中国科学技术大学 · 导师研究星图",
        "generated_at": rag.get("generated_at") or rag.get("run_date") or "未知",
        "source_chain": rag.get("source_chain") or [],
        "mentor_count": len(nodes),
        "evidence_count": rag.get("evidence_count", 0),
        "domain_count": len(legend),
        "departments": sorted({n["department"] for n in nodes}),
        "legend": legend,
        # 代表点示例（用于前端默认相机定位等）
        # 扁平螺旋盘的内/外半径——前端据此设定默认相机距离，保证总览看全盘
        "camera": {"target": [0, 0, 0], "radius": 1500, "r_out": R_OUT, "r_in": R_IN, "arms": N_ARMS},
        "layout": {
            "algorithm": "balanced_double_orbit_v4",
            "galaxy_spacing": R_OUT,
            "cloud_scale": 70,
            "disk_radius": R_OUT,
            "arms": N_ARMS,
        },
        "classification": {
            "strategy": "keyword_score_desc_v2",
            "classified_count": sum(1 for n in nodes if n["classification_status"] == "classified"),
            "unclassified_count": sum(1 for n in nodes if n["classification_status"] == "unclassified"),
        },
    }

    out = {"meta": meta, "nodes": nodes}
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print(f"[OK] 已生成 {out_path}")
    print(f"     导师 {len(nodes)} 位 · 领域 {len(legend)} 个 · 证据 {meta['evidence_count']} 条")
    for d in legend:
        print(f"   {d['name']:<10} {d['color']}  {d['count']} 位")
    return out


def gauss3():
    """标准正态分布三维向量（Box-Muller 近似，用于云团核心密边缘疏）。"""
    u1 = random.random() or 1e-9
    u2 = random.random()
    r = math.sqrt(-2.0 * math.log(u1))
    th = 2.0 * math.pi * u2
    # 三维：
    u3 = random.random() or 1e-9
    u4 = random.random()
    r2 = math.sqrt(-2.0 * math.log(u3))
    th2 = 2.0 * math.pi * u4
    return (r*math.cos(th), r2*math.sin(th2), r2*math.cos(th2))


def star_size(c):
    """导师节点大小：由研究方向+论文丰富度决定。"""
    base = 1.0
    if c.get("research_topics"):
        base += min(1.0, len(c["research_topics"]) * 0.2)
    pubs = len(c.get("publications") or [])
    base += min(1.5, pubs * 0.12)
    return round(base, 3)


def luminance(c, domain):
    """节点相对亮度 0.55~1.0：研究方向多/论文多的"学术明星"更亮。
    用于前端同色系内做明暗层次，增强银河纵深。"""
    score_total = 0.0
    if c.get("research_topics"):
        score_total += min(1.2, len(c["research_topics"]) * 0.25)
    pubs = len(c.get("publications") or [])
    score_total += min(1.5, pubs * 0.1)
    # 所在的领域大小也略微影响（大领域中的个体相对平均）
    return round(0.55 + 0.45 * min(1.0, score_total), 3)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    rag_path = os.path.join(here, "..", "paper-claw-master", "data", "ustc_mentor_rag.json")
    out_path = os.path.join(here, "cloud_data.json")

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--rag" and i + 1 < len(args):
            rag_path = args[i + 1]; i += 2
        elif args[i] == "--out" and i + 1 < len(args):
            out_path = args[i + 1]; i += 2
        else:
            i += 1

    random.seed(42)  # 可复现
    build(rag_path, out_path)


if __name__ == "__main__":
    main()
