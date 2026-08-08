#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_cloud.py — 导师 3D 星图数据生成脚本（纯 Python 标准库，无第三方依赖）

每次运行时重新读取最新 RAG 数据库 data/ustc_mentor_rag.json，
计算每个导师的研究领域得分 / 球面 3D 坐标 / 学院映射 / 领域配色，
输出前端可直接加载的 cloud_data.json。

数据分离：
  build_cloud.py  (生成)  -->>  cloud_data.json  <!-- index.html (展示, Three.js)
正式前端可复用同一份 cloud_data.json，接口稳定。

用法:  py build_cloud.py  [--rag PATH] [--out PATH]
默认读取 ../data/ustc_mentor_rag.json，输出 ./cloud_data.json
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
# 用于把 715 位导师粗分为 ~10 个研究版图。关键词覆盖 department / topics / methods。
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


def domain_scores(text_blocks):
    """返回 [(domain, score)]，按得分降序。score = 命中关键词总数(去重)。"""
    text = " ".join(t or "" for t in text_blocks).lower()
    scored = []
    for d in DOMAINS:
        n = sum(1 for k in d["keys"] if k.lower() in text)
        if n > 0:
            scored.append((d, n))
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
        primary = s[0][0] if s else DOMAINS[0]
        # 次领域（用于微调方向）
        secondary = s[1][0] if len(s) > 1 else None
        scored.append((c, primary, secondary, s))

    # 2) 每个领域分配到「银河系扁平螺旋盘」的一条悬臂上的一个弧段
    #    —— 扁平圆盘(XZ 平面为主) + 6 条对数螺旋悬臂 + 一定竖直厚度(Y 轻微散开)
    by_domain = defaultdict(list)
    for c, primary, secondary, s in scored:
        by_domain[primary["id"]].append((c, primary, secondary, s))
    max_cnt = max(len(m) for m in by_domain.values()) if by_domain else 1

    N_ARMS = 4          # 4 条主对数螺旋悬臂（让四大主旋臂清晰）
    R_IN  = 170.0       # 螺旋盘内半径（背景装饰用）
    R_OUT = 540.0       # 螺旋盘外半径
    TURNS = 1.4         # 每条悬臂缠绕圈数
    TURNOVER = TURNS * 2 * math.pi
    TOV_DEG = TURNOVER * 180.0 / math.pi   # 一整条臂缠绕的总角度

    # ---- 需求2（本轮）：10 领域分布到 4 条主旋臂，星点在臂中心线两侧展开 ----
    #  1) 按人口降序 rank=0..9；人口越多越靠内。10 领域显式分到 4 臂（≈3+3+2+2），
    #     各臂人口大致均衡，避免都堆到一条臂上。
    #  2) 每领域落在所属臂的一段径向带上（tc 由目标半径反解对数螺旋参数）。
    #  3) 关键：星点除沿臂径向高斯延续外，还在【垂直于臂走向的横向方向】两侧展开
    #     （u 沿局部法向 n̂ 高斯散布），使"星星骑在臂上"而不是正中一条线。
    #  4) 领域目标半径下限 R_CORE_EDGE 抬到 ~250，避开中央模糊星云占用的内核，
    #     保证 4 条臂的领域可分辨、不被星云吞没。
    pop_rank = sorted(by_domain.items(), key=lambda kv: -len(kv[1]))  # [(dom_id,members)] 人口降序
    rank_of = {dom_id: r for r, (dom_id, _) in enumerate(pop_rank)}
    N_dom = len(by_domain)
    R_CORE_EDGE = 250.0   # 领域最内核缘（人口最多最靠里，但仍然在中央星云之外）
    R_RIM_EDGE  = 460.0   # 领域最外缘（不到盘缘）

    def target_radius(rank):
        frac = rank / max(1, N_dom - 1)
        return R_CORE_EDGE + frac * (R_RIM_EDGE - R_CORE_EDGE)

    # rank -> 主旋臂 0..3（3+3+2+2），各臂人口大致均衡：
    #   arm0: physics(239)+manage(26)+math(24)≈289
    #   arm1: chemistry(114)+bio(40)+energy(24)≈178
    #   arm2: info(91)+cs(36)≈127
    #   arm3: geo(64)+engineering(57)≈121
    ARM_BY_RANK = {0:0, 8:0, 7:0,   1:1, 5:1, 9:1,   2:2, 6:2,   3:3, 4:3}

    ARM_PLAN = {}
    for dom_id, members in by_domain.items():
        rank = rank_of[dom_id]
        arm = ARM_BY_RANK[rank]
        r_des = target_radius(rank)
        tc = math.log(r_des / R_IN) / math.log(R_OUT / R_IN)  # 半径→螺旋参数
        tc = max(0.10, min(0.92, tc))
        # 沿臂径向的半带宽（t 尺度）：人口多更紧致，少则清晰；同臂领域 t 间隙远大于 seg
        seg = 0.030 + 0.026 * (len(members) / max_cnt)
        # 横向（垂直臂走向）散布半宽：人口多更宽，让星簇"骑"在臂两侧
        trans = 16 + 26 * (len(members) / max_cnt)
        ARM_PLAN[dom_id] = (arm, tc, seg, trans)

    def spiral_phase(arm):
        return arm * 2 * math.pi / N_ARMS

    # 竖直厚度：透镜状剖面——内缘鼓、外缘收，扁盘带明显 3D 弧面感
    def thickness(jt):
        jt = max(0.0, min(1.0, jt))
        inner = 26.0
        outer = 13.0
        k = max(0.0, min(1.0, (jt - 0.2) / 0.6))
        return inner - (inner - outer) * k

    # 3) 生成每个导师的坐标：沿所属悬臂的一段径向带，并在臂中心线两侧横向展开
    nodes = []
    for dom_id, members in by_domain.items():
        arm, tc, seg, trans = ARM_PLAN.get(dom_id, (0, 0.5, 0.1, 20.0))
        count = len(members)
        cloud_r = 8 + 10 * min(1.0, count / max_cnt)
        phase = spiral_phase(arm)
        for c, primary, secondary, s in members:
            # 沿臂进度 t：高斯聚在径向带中央（核心密、两端疏）
            t = tc + random.gauss(0, 1) * seg * 0.5
            t = max(tc - seg, min(tc + seg, t))
            # 臂中心线位置
            r_base = R_IN * (R_OUT / R_IN) ** t
            th_c = phase + t * TURNOVER
            cx_, cz_ = r_base * math.cos(th_c), r_base * math.sin(th_c)
            # 臂切线方向（沿参数 t 的导数），用于算横向法向 n̂
            drdt = r_base * math.log(R_OUT / R_IN)
            tx = drdt * math.cos(th_c) - r_base * TURNOVER * math.sin(th_c)
            tz = drdt * math.sin(th_c) + r_base * TURNOVER * math.cos(th_c)
            tl = math.sqrt(tx * tx + tz * tz) or 1.0
            # 盘面内垂直切线的法向：n̂=(-t̂z, 0, t̂x)
            nx, nz = -tz / tl, tx / tl
            # 横向散布 u（±，向臂中心线两侧）：核心密、两侧疏
            u = random.gauss(0, 1) * trans * 0.5
            u = max(-trans, min(trans, u))
            # 另加少量沿臂径向抖动（云团尺度）
            gx = random.gauss(0, 1); gy = random.gauss(0, 1); gz = random.gauss(0, 1)
            px = cx_ + u * nx + gx * cloud_r
            pz = cz_ + u * nz + gz * cloud_r
            r = math.hypot(px, pz)
            # 竖直方向透镜状厚度（中心鼓、边缘收）
            jt = max(0.0, min(1.0, (r - R_IN) / (R_OUT - R_IN)))
            py = gy * thickness(jt)
            # 需求1：径向亮度因子——越靠近中心模糊星云越亮（幂次衰减），
            # 供前端把星点/尘埃亮度整体压向中心，形成「越近越亮」的银河纵深。
            r_norm0 = max(0.0, min(1.0, (r - R_IN) / (R_OUT - R_IN)))
            core_lum = round((1.0 - r_norm0) ** 1.6, 3)   # 中心1.0 → 外缘0
            nodes.append({
                "candidate_id": c["candidate_id"],
                "name": c.get("mentor_name") or "",
                "department": c.get("department") or "",
                "affiliation": c.get("affiliation") or "",
                "domain": primary["id"],
                "domain_name": primary["name"],
                "secondary": secondary["name"] if secondary else None,
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
    legend = [{"id": d["id"], "name": d["name"], "color": d["color"],
               "count": dom_counts.get(d["id"], 0)}
              for d in DOMAINS]
    legend.sort(key=lambda x: -x["count"])

    # 5) 顶层元信息 + 统计
    meta = {
        "title": "中国科学技术大学 · 导师研究星图",
        "generated_at": rag.get("generated_at") or rag.get("run_date") or "未知",
        "source_chain": rag.get("source_chain") or [],
        "mentor_count": len(nodes),
        "evidence_count": rag.get("evidence_count", 0),
        "domain_count": len(DOMAINS),
        "departments": sorted({n["department"] for n in nodes}),
        "legend": legend,
        # 代表点示例（用于前端默认相机定位等）
        # 扁平螺旋盘的内/外半径——前端据此设定默认相机距离，保证总览看全盘
        "camera": {"target": [0, 0, 0], "radius": 1500, "r_out": R_OUT, "r_in": R_IN, "arms": N_ARMS},
        "layout": {"galaxy_spacing": R_OUT, "cloud_scale": 70, "disk_radius": R_OUT, "arms": N_ARMS},
    }

    out = {"meta": meta, "nodes": nodes}
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print(f"[OK] 已生成 {out_path}")
    print(f"     导师 {len(nodes)} 位 · 领域 {len(DOMAINS)} 个 · 证据 {meta['evidence_count']} 条")
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