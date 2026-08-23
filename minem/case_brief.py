"""Stable case-generation brief shared by MineM CLI and AI agents."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


CASE_BRIEF_SCHEMA_VERSION = "minem.case-brief/v1"
DEFAULT_MAX_CASES = 3
MAX_CASES_LIMIT = 12


CASE_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["source", "caseGroupTitle", "cases", "excludedCandidates"],
    "properties": {
        "source": {"type": "string"},
        "caseGroupTitle": {"type": "string"},
        "cases": {
            "type": "array",
            "maxItems": MAX_CASES_LIMIT,
            "items": {
                "type": "object",
                "required": [
                    "caseName",
                    "pageTitle",
                    "scenario",
                    "background",
                    "pain",
                    "solution",
                    "result",
                    "storyline",
                    "attachments",
                    "sourceUrl",
                ],
                "properties": {
                    "caseName": {"type": "string"},
                    "award": {"type": "string"},
                    "pageTitle": {"type": "string"},
                    "scenario": {"type": "string"},
                    "background": {"type": "string"},
                    "pain": {"type": "string"},
                    "solution": {"type": "string"},
                    "result": {"type": "string"},
                    "storyline": {"type": "string"},
                    "score": {
                        "type": "object",
                        "properties": {
                            "businessImpact": {"type": "integer", "minimum": 0, "maximum": 3},
                            "evidenceStrength": {"type": "integer", "minimum": 0, "maximum": 3},
                            "beforeAfterClarity": {"type": "integer", "minimum": 0, "maximum": 2},
                            "reusability": {"type": "integer", "minimum": 0, "maximum": 2},
                            "total": {"type": "integer", "minimum": 0, "maximum": 10},
                        },
                    },
                    "attachments": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["kind", "source", "module", "proof"],
                            "properties": {
                                "kind": {"enum": ["video", "gif", "table", "image", "file"]},
                                "source": {"type": "string"},
                                "module": {"enum": ["background", "pain", "solution", "result", "modal"]},
                                "proof": {"type": "string"},
                                "interaction": {"enum": ["inline", "lightbox", "play", "download"]},
                                "poster": {"type": "string"},
                                "caption": {"type": "string"},
                            },
                        },
                    },
                    "pagePlan": {
                        "type": "object",
                        "properties": {
                            "pageCount": {"type": "integer", "minimum": 1, "maximum": 4},
                            "reason": {"type": "string"},
                            "layout": {"type": "string"},
                            "heroAsset": {"type": "string"},
                            "modalAssets": {"type": "array", "items": {"type": "string"}},
                            "pages": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 4,
                                "items": {
                                    "type": "object",
                                    "required": ["purpose", "title", "assetRefs"],
                                    "properties": {
                                        "purpose": {"enum": ["overview", "before-after", "workflow", "results", "evidence"]},
                                        "title": {"type": "string"},
                                        "layout": {"type": "string"},
                                        "assetRefs": {"type": "array", "items": {"type": "string"}},
                                    },
                                },
                            },
                        },
                    },
                    "sourceUrl": {"type": "string"},
                },
            },
        },
        "excludedCandidates": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title", "reason"],
                "properties": {"title": {"type": "string"}, "reason": {"type": "string"}},
            },
        },
    },
}


def build_case_brief(
    source: str,
    *,
    audience: str = "管理层",
    focus: str = "",
    max_cases: int = DEFAULT_MAX_CASES,
) -> dict[str, Any]:
    """Return the deterministic case-selection and generation contract."""

    source = str(source or "").strip()
    audience = str(audience or "管理层").strip() or "管理层"
    focus = str(focus or "").strip()
    if not source:
        raise ValueError("A source document URL or local path is required")
    if max_cases < 1 or max_cases > MAX_CASES_LIMIT:
        raise ValueError(f"max_cases must be between 1 and {MAX_CASES_LIMIT}")

    focus_line = focus or "优先选择业务价值高、证据完整、可复用性强的案例"
    prompt = f"""你是 MineM 案例素材生成 Agent。请基于来源文档生成面向{audience}的案例素材。

来源：{source}
重点：{focus_line}
最多发布：{max_cases} 个案例；这是上限，不是凑数目标。

必须按以下流程执行：
1. 结构扫描：识别章节、业务对象、流程、数字、表格、图片、视频、GIF 与来源锚点。
2. 候选聚合：按同一业务对象和同一成果链路合并相邻章节；禁止把每个标题机械地变成案例。
3. 候选评分：业务影响 0–3、证据强度 0–3、前后对比 0–2、复用价值 0–2，总分低于 6 不发布。
4. 只选择得分最高且叙事完整的最多 {max_cases} 个案例；若只有 1 个好案例就只生成 1 个。
5. 每个案例形成“背景 → 痛点 → 方案 → 结果”的闭环；根据证据数量和可读性自适应生成 1–4 张 1920×1080 页面，不把不同案例混在同一页。

事实与素材规则：
- 只使用原文能够直接证明的事实、数字、奖项和结论；不得补写指标、客户评价或收入成果。
- 图片、视频、GIF、表格必须归属到具体案例和 background/pain/solution/result 模块；跨案例素材不得混用。
- 优先级：实际流程视频或 GIF > 结果表格 > before/after > 产品界面或流程图 > 次要图片。
- 有原文图片时优先原图，不用转述截图或无关装饰图；团队合影、赛事介绍和通用方法论不能单独成为案例。
- 不要为了压缩成一页只保留一张图片。与案例直接相关、质量良好且能证明客户场景/流程/成果的素材都要纳入页面规划。
- 每页选择一个主证据素材，其余强证据可进入独立补充页或可展开区域；没有直接证据时不要硬配图。
- 视频必须以真实可播放资源入库，点击后在页面或媒体查看器中播放，显示原生控制条并支持暂停、进度和全屏；禁止自动播放，加载失败时提供打开原视频入口。
- GIF 保留动画，图片点击查看原图；视频封面、图片和表格都要标明它们证明的业务信息。

页面与平台规则：
- 使用结论型标题，首屏突出最可信的业务变化；页面保持深色、紧凑、管理层可扫描。
- 主证据应与它证明的模块相邻，保持原始比例和可读性。
- 一页能够清楚表达背景、机制和结果时使用单页；存在可播放视频、多组 before/after、独立结果表格或多组优秀客户素材时拆为 2–4 页，不挤压关键信息。
- 多页顺序优先采用：案例概览 → before/after → 工作流或视频演示 → 结果与客户证据。没有对应证据的页面不得空生成。
- 每个页面保存原始文档链接；由 MineM 查看器提供复制原文入口和 1 秒成功提示，不在页面内重复平台工具栏。
- 每张页面正式入库为 page material，每个附件正式入库为 resource material；案例组不是 report material。
- 只发布入选案例。其他候选写入 excludedCandidates 及原因，不生成页面。

请严格按照随 CLI 返回的 outputSchema 输出结构化结果。"""

    output_schema = deepcopy(CASE_OUTPUT_SCHEMA)
    output_schema["properties"]["cases"]["maxItems"] = max_cases

    return {
        "schemaVersion": CASE_BRIEF_SCHEMA_VERSION,
        "profile": "evidence-first-executive-case",
        "source": source,
        "audience": audience,
        "focus": focus_line,
        "requestedMaxCases": max_cases,
        "defaults": {
            "maxCases": DEFAULT_MAX_CASES,
            "minimumPublishScore": 6,
            "pagesPerCase": {"mode": "adaptive", "minimum": 1, "maximum": 4},
            "canvas": {"width": 1920, "height": 1080},
        },
        "selectionPolicy": {
            "doNotSplitByHeading": True,
            "doNotPadToLimit": True,
            "mergeOverlappingSections": True,
            "score": [
                {"name": "businessImpact", "max": 3},
                {"name": "evidenceStrength", "max": 3},
                {"name": "beforeAfterClarity", "max": 2},
                {"name": "reusability", "max": 2},
            ],
            "minimumPublishScore": 6,
        },
        "mediaPolicy": {
            "directEvidenceOnly": True,
            "preferOriginalMedia": True,
            "includeAllStrongCustomerEvidence": True,
            "onePrimaryAssetPerPage": True,
            "mapEveryAssetToModule": True,
            "videoInteraction": "click-to-play with controls, pause, seek, fullscreen, poster, and fallback link; never autoplay",
            "gifPlayback": "preserve animation",
            "exclude": ["unrelated media", "team photos", "event boilerplate", "cross-case assets"],
            "priority": ["workflow video or GIF", "result table", "before/after", "interface or process image", "secondary modal media"],
        },
        "pagePolicy": {
            "oneCasePerPage": True,
            "adaptivePagesPerCase": True,
            "singlePageOnlyWhenSufficient": True,
            "maxPagesPerCase": 4,
            "style": "dark, dense, executive, presentation-ready",
            "storyOrder": ["background", "pain", "solution", "result"],
            "sourceLinkRequired": True,
            "viewerOwnsSourceCopyToast": True,
            "imageLightboxRequired": True,
            "videoPlaybackRequired": True,
            "noNestedViewerToolbar": True,
        },
        "outputSchema": output_schema,
        "prompt": prompt,
        "workflow": [
            "Read source and produce structured candidates using this brief",
            "Plan 1-4 pages per selected case from the evidence, then publish each page specification with minem page build --publish",
            "Import directly related evidence as resource material",
            "Register one case group that references the published page codes and source URL",
            "Verify case list, page assets, resource assets, source copy, image lightbox, video playback, GIF animation, and GET reachability",
        ],
    }
