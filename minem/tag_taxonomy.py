"""Controlled business taxonomy and deterministic tag classification."""
from __future__ import annotations

import re
from collections import defaultdict


TAXONOMY_VERSION = "taxonomy-v1"
MODEL_VERSION = "rules-v1"
MIN_CONFIRM_CONFIDENCE = 0.70
MAX_CONFIRMED_TAGS = 4
# Per PRD 4.5 rule 4: when two mutually exclusive candidates in one dimension are
# within this raw-score gap, the winner is ambiguous, so it is flagged "conflict"
# and withheld from automatic confirmation instead of being auto-applied.
CONFLICT_SCORE_GAP = 0.15

TAXONOMY = {
    "内容角色": ["封面", "目录", "问题", "价值", "方案", "案例", "数据", "流程", "总结", "行动"],
    "使用场景": ["经营汇报", "客户拜访", "项目复盘", "产品发布", "内部培训", "方案宣讲"],
    "目标对象": ["CEO", "管理层", "销售", "客户", "一线员工", "技术团队"],
    "行业": ["制造", "零售", "互联网", "金融", "医疗", "教育", "通用"],
    "业务主题": ["AI 转型", "组织协同", "效率提升", "数字员工", "客户增长", "质量管理", "风险管理"],
}

TAG_DIMENSION = {tag: dimension for dimension, tags in TAXONOMY.items() for tag in tags}
CONTROLLED_TAGS = frozenset(TAG_DIMENSION)
FORBIDDEN_TAGS = frozenset({
    "汇报素材", "页面素材", "资源素材", "控件素材", "完整汇报", "HTML汇报", "HTML 汇报",
    "上传", "upload", "图片", "视频", "图标", "Logo", "GIF", "SVG", "HTML",
    "当前版本", "自动同步", "系统合并", "人工合并",
})

# A match contributes once per pattern. More specific phrases are listed first.
RULES = {
    "封面": [r"\bcover\b", r"封面", r"汇报人", r"报告人"],
    "目录": [r"\bagenda\b", r"目录", r"contents?", r"章节"],
    "问题": [r"痛点", r"问题", r"挑战", r"现状", r"瓶颈", r"不足"],
    "价值": [r"\broi\b", r"价值", r"收益", r"效益", r"回报", r"提升.{0,8}(?:率|效|量)"],
    "方案": [r"解决方案", r"总体方案", r"实施方案", r"架构", r"能力地图", r"产品矩阵"],
    "案例": [r"客户案例", r"典型案例", r"实践案例", r"案例", r"标杆"],
    "数据": [r"数据分析", r"趋势", r"同比", r"环比", r"指标", r"\b\d+(?:\.\d+)?%"],
    "流程": [r"业务流程", r"流程", r"步骤", r"阶段", r"闭环", r"链路"],
    "总结": [r"总结", r"回顾", r"结论", r"关键发现", r"要点"],
    "行动": [r"下一步", r"行动计划", r"推进计划", r"待办", r"里程碑"],
    "经营汇报": [r"经营汇报", r"经营分析", r"经营情况", r"管理驾驶舱", r"业务复盘"],
    "客户拜访": [r"客户拜访", r"客户沟通", r"售前", r"商机", r"客户交流"],
    "项目复盘": [r"项目复盘", r"复盘", r"项目总结", r"经验沉淀"],
    "产品发布": [r"产品发布", r"新品发布", r"发布会", r"产品介绍"],
    "内部培训": [r"内部培训", r"培训", r"研修班", r"课程", r"学习"],
    "方案宣讲": [r"方案宣讲", r"解决方案", r"提案", r"路演"],
    "CEO": [r"\bceo\b", r"首席执行官", r"总裁", r"董事长"],
    "管理层": [r"管理层", r"高管", r"管理者", r"决策层", r"负责人"],
    "销售": [r"销售团队", r"销售", r"营销", r"商机", r"客户经理"],
    "客户": [r"客户", r"用户", r"消费者", r"合作伙伴"],
    "一线员工": [r"一线员工", r"一线人员", r"店员", r"工人", r"员工"],
    "技术团队": [r"技术团队", r"研发", r"开发者", r"工程师", r"\bit\b"],
    "制造": [r"制造业", r"制造", r"工厂", r"产线", r"生产", r"供应链"],
    "零售": [r"零售", r"门店", r"导购", r"商品", r"电商"],
    "互联网": [r"互联网", r"平台业务", r"流量", r"内容平台"],
    "金融": [r"金融", r"银行", r"保险", r"证券", r"风控"],
    "医疗": [r"医疗", r"医院", r"患者", r"临床", r"医药"],
    "教育": [r"教育", r"学校", r"教师", r"学生", r"课程"],
    "AI 转型": [r"人工智能", r"\bai\b", r"智能化转型", r"数智化", r"智能化升级"],
    "组织协同": [r"组织协同", r"协同", r"组织能力", r"跨部门", r"团队协作"],
    "效率提升": [r"效率提升", r"提效", r"降本增效", r"生产力", r"自动化"],
    "数字员工": [r"数字员工", r"智能体", r"\bagent\b", r"数字人", r"机器人助手"],
    "客户增长": [r"客户增长", r"用户增长", r"增长", r"获客", r"转化率", r"复购"],
    "质量管理": [r"质量管理", r"质量", r"质检", r"良率", r"品质"],
    "风险管理": [r"风险管理", r"风险", r"合规", r"审计", r"安全事件", r"预警"],
}

COMPILED_RULES = {
    tag: [re.compile(pattern, re.I) for pattern in patterns]
    for tag, patterns in RULES.items()
}


def taxonomy_payload():
    return {
        "version": TAXONOMY_VERSION,
        "dimensions": [
            {"name": dimension, "tags": tags}
            for dimension, tags in TAXONOMY.items()
        ],
        "minimumConfirmConfidence": MIN_CONFIRM_CONFIDENCE,
        "maximumConfirmedTags": MAX_CONFIRMED_TAGS,
    }


def validate_tags(tags):
    normalized = []
    for tag in tags:
        value = str(tag or "").strip()
        if value in CONTROLLED_TAGS and value not in normalized:
            normalized.append(value)
    return normalized[:MAX_CONFIRMED_TAGS]


def _source_text(source):
    parts = [source.get("title") or "", source.get("text") or ""]
    parts.extend(source.get("headings") or [])
    for item in source.get("items") or []:
        if isinstance(item, dict):
            parts.extend(str(item.get(key) or "") for key in ("asset_code", "title", "usage", "snippet"))
    return " ".join(parts)


def classify_evidence(evidence):
    scores = defaultdict(float)
    matches = defaultdict(list)
    priority_weight = {"P1": 1.0, "P2": 0.76, "P3": 0.62, "P4": 0.34, "P5": 0.12}

    for source in evidence.get("sources") or []:
        priority = source.get("priority") or "P5"
        weight = priority_weight.get(priority, 0.12)
        text = _source_text(source)
        if not text:
            continue
        for tag, patterns in COMPILED_RULES.items():
            hit_count = sum(1 for pattern in patterns if pattern.search(text))
            if not hit_count:
                continue
            contribution = weight * min(1.0, 0.58 + 0.20 * (hit_count - 1))
            scores[tag] += contribution
            matches[tag].append({
                "priority": priority,
                "sourceType": source.get("type") or "",
                "matches": hit_count,
            })

    candidates = []
    for tag, score in scores.items():
        confidence = min(0.96, 0.60 + score * 0.22)
        candidates.append({
            "dimension": TAG_DIMENSION[tag],
            "tag": tag,
            "confidence": round(confidence, 3),
            "evidence": matches[tag][:6],
            "conflictStatus": "none",
            "_score": score,
        })

    # The taxonomy permits multiple values per dimension. The automatic confirmation
    # stage still selects only the strongest value in each dimension.
    by_dimension = defaultdict(list)
    for candidate in candidates:
        by_dimension[candidate["dimension"]].append(candidate)
    for dimension_candidates in by_dimension.values():
        dimension_candidates.sort(key=lambda item: (-item["_score"], item["tag"]))
        # Flag intra-dimension ambiguity by raw-score gap (PRD 4.5 rule 4): if a
        # runner-up is within the gap of the leader, neither is trustworthy
        # enough to auto-confirm, so both are marked "conflict".
        if len(dimension_candidates) >= 2:
            leader = dimension_candidates[0]
            for other in dimension_candidates[1:]:
                if leader["_score"] - other["_score"] < CONFLICT_SCORE_GAP:
                    leader["conflictStatus"] = "conflict"
                    other["conflictStatus"] = "conflict"

    confirmed_industry = any(
        item["confidence"] >= MIN_CONFIRM_CONFIDENCE and item["conflictStatus"] == "none"
        for item in by_dimension.get("行业", [])
    )
    if not confirmed_industry:
        fallback = {
            "dimension": "行业",
            "tag": "通用",
            "confidence": MIN_CONFIRM_CONFIDENCE,
            "evidence": [{"priority": "P4", "sourceType": "taxonomy_fallback", "matches": 1}],
            "conflictStatus": "none",
        }
        candidates.append(fallback)
        by_dimension["行业"].append(fallback)

    candidates.sort(key=lambda item: (-item["confidence"], item["dimension"], item["tag"]))
    for candidate in candidates:
        candidate.pop("_score", None)
    return candidates


def confirmed_candidates(candidates):
    selected = []
    used_dimensions = set()
    for candidate in candidates:
        if candidate["confidence"] < MIN_CONFIRM_CONFIDENCE:
            continue
        if candidate.get("conflictStatus") != "none":
            continue
        if candidate["dimension"] in used_dimensions:
            continue
        selected.append(candidate)
        used_dimensions.add(candidate["dimension"])
        if len(selected) >= MAX_CONFIRMED_TAGS:
            break
    return selected
