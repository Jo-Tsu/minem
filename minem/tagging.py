import re
import sqlite3


def split_tags(value):
    return [tag.strip() for tag in (value or "").split(",") if tag.strip()]


def merge_tags(*tag_groups):
    seen = set()
    merged = []
    for group in tag_groups:
        if isinstance(group, str):
            tags = split_tags(group)
        else:
            tags = [tag for tag in group if tag]
        for tag in tags:
            if tag not in seen:
                seen.add(tag)
                merged.append(tag)
    return merged


def allowed_logo_subtags(identity_text):
    probe = (identity_text or "").lower()
    allowed = {"品牌标识"}
    if any(word in probe for word in ["飞书", "feishu", "lark"]):
        allowed.add("飞书logo")
    if any(word in probe for word in ["partner", "合作伙伴", "slack", "google", "amazon", "netflix", "skype", "dingtalk"]):
        allowed.add("合作伙伴logo")
    if any(word in probe for word in ["客户", "client", "customer", "cxmt", "长鑫", "蔚来", "继峰", "海亮", "宝龙达", "顺达", "米飞泰克斯"]):
        allowed.add("客户logo")
    return allowed


def allowed_icon_subtags(identity_text):
    probe = (identity_text or "").lower()
    allowed = set()
    if any(word in probe for word in ["飞书", "feishu", "lark"]):
        allowed.update(["飞书产品", "协作工具"])
    if any(word in probe for word in ["slack", "google", "amazon", "netflix", "skype", "dingtalk", "mail", "doc", "sheet"]):
        allowed.update(["第三方产品", "协作工具"])
    if any(word in probe for word in ["ai", "aily", "agent", "robot", "bot", "智能", "机器人"]):
        allowed.add("AI产品")
    if any(word in probe for word in ["admin", "manage", "management", "管理", "组织", "权限"]):
        allowed.add("管理工具")
    return allowed


def normalize_role_tags(
    tags,
    asset_type,
    resource_kind="",
    identity_text="",
    *,
    resource_structure_tags=(),
    reference_tags=(),
    identity_media_excluded_tags=(),
    logo_role_tags=(),
    icon_role_tags=(),
    icon_subtype_tags=(),
):
    allowed_subtypes = allowed_logo_subtags(identity_text) if asset_type == "resource" and resource_kind == "logo" and identity_text else None
    allowed_icon_types = allowed_icon_subtags(identity_text) if asset_type == "resource" and resource_kind == "icon" and identity_text else None
    original_tags = merge_tags(tags)
    has_direct_use = "可直接使用" in set(original_tags)
    cleaned = []
    for tag in original_tags:
        if has_direct_use and tag == "不可直接使用":
            continue
        if asset_type == "resource" and tag in resource_structure_tags:
            continue
        if asset_type == "resource" and resource_kind in {"logo", "icon"} and tag in reference_tags:
            continue
        if asset_type == "resource" and resource_kind in {"logo", "icon"} and tag in identity_media_excluded_tags:
            continue
        if asset_type == "resource" and resource_kind in {"gif", "video"} and tag in {"页面背景", "封面背景", "内容页背景", "深色科技风"}:
            continue
        if asset_type == "resource" and resource_kind != "logo" and tag in logo_role_tags:
            continue
        if asset_type == "resource" and resource_kind != "icon" and tag in icon_role_tags:
            continue
        if allowed_subtypes is not None and tag in {"客户logo", "飞书logo", "合作伙伴logo"} and tag not in allowed_subtypes:
            continue
        if allowed_icon_types is not None and tag in icon_subtype_tags and tag not in allowed_icon_types:
            continue
        if asset_type == "report" and tag in {"基础资源", "资源素材", "图片素材", "视频素材", "GIF素材", "SVG素材", "产品icon", "企业logo"}:
            continue
        if asset_type == "control" and tag in {"完整汇报", "HTML汇报", "可导出", "基础资源", "资源素材"}:
            continue
        cleaned.append(tag)
    return cleaned


def infer_tags(asset, *, categories, tag_rules, asset_library_path, image_trait_tags_fn=None):
    image_trait_tags_fn = image_trait_tags_fn or image_trait_tags
    text = " ".join([
        asset["title"] or "",
        asset["usage"] or "",
        asset["source_path"] or "",
        asset["snippet"] or "",
        asset["category"] or "",
        asset["media_kind"] or "",
        asset["resource_kind"] or "",
        asset["source_type"] or "",
    ]).lower()
    tags = []
    if asset["asset_type"] == "report":
        tags.extend(["汇报素材", "完整汇报", "HTML汇报", "可导出"])
    elif asset["asset_type"] == "control":
        tags.extend(["页面素材", "单页素材", "可拼接页面", "页面片段"])
    elif asset["asset_type"] == "resource":
        tags.extend(["资源素材", "基础资源"])
        media_kind = asset["media_kind"] or ""
        resource_kind = asset["resource_kind"] or ""
        if media_kind == "image":
            tags.append("图片素材")
        elif media_kind == "video":
            tags.append("视频素材")
        elif media_kind == "gif":
            tags.append("GIF素材")
        elif media_kind == "svg":
            tags.append("SVG素材")
        if resource_kind == "logo":
            tags.extend(["企业logo", "品牌标识", "可直接使用"])
        elif resource_kind == "icon":
            tags.extend(["产品icon", "可直接使用"])
        elif resource_kind == "video":
            tags.extend(["视频素材", "可直接使用"])
        elif resource_kind == "gif":
            tags.extend(["GIF素材", "可直接使用"])
        if resource_kind not in {"logo", "icon"} and any(word in text for word in ["dashboard", "screen", "screenshot", "界面", "截图", "控制台", "demo", "phone"]):
            tags.extend(["参考截图", "产品截图", "页面截图"])
        if any(word in text for word in ["photo", "camera", "poster", "现场", "工厂", "车间", "人物", "头像"]):
            tags.append("实景照片")
        if any(word in text for word in ["illustration", "shape", "decor", "装饰", "插画"]):
            tags.append("装饰插画")
        path = asset_library_path(asset)
        if path and path.exists() and media_kind in {"image", "gif"}:
            tags.extend(image_trait_tags_fn(path))
    category_label = categories.get(asset["category"])
    if category_label:
        tags.append(category_label)
    tags.extend(source_process_tags(asset["source_type"]))
    tags.extend(page_usage_tags(text))
    for label, keywords in tag_rules:
        if any(keyword.lower() in text for keyword in keywords):
            tags.append(label)
    if "iframe" in text:
        tags.append("iframe 嵌入")
    if "chat" in text or "对话" in text:
        tags.append("对话场景")
    if "timeline" in text or "时间线" in text:
        tags.append("时间线")
    if "kpi" in text or "metric" in text or "指标" in text:
        tags.append("KPI")
    return merge_tags(tags)


def infer_tags_from_text(text, *, tag_rules):
    probe = (text or "").lower()
    tags = []
    for label, keywords in tag_rules:
        if any(keyword.lower() in probe for keyword in keywords):
            tags.append(label)
    for token in re.split(r"[\s,，、;；/|]+", text or ""):
        token = token.strip("#：:。.!！?？")
        if 2 <= len(token) <= 12 and not re.search(r"[<>={}()]", token):
            tags.append(token)
        if len(tags) >= 10:
            break
    return merge_tags(tags)


def image_traits(path, *, image_module=None, image_sequence_module=None):
    if image_module is None:
        return {}
    try:
        image = image_module.open(path)
        if getattr(image, "is_animated", False) and image_sequence_module is not None:
            image.seek(0)
        width, height = image.size
        has_alpha = image.mode in {"RGBA", "LA"} or ("transparency" in image.info)
        return {"width": width, "height": height, "has_alpha": has_alpha}
    except Exception:
        return {}


def image_trait_tags(path, *, image_module=None, image_sequence_module=None):
    traits = image_traits(path, image_module=image_module, image_sequence_module=image_sequence_module)
    width = traits.get("width") or 0
    height = traits.get("height") or 0
    tags = []
    if traits.get("has_alpha"):
        tags.append("透明底")
    if width and height:
        ratio = width / height if height else 1
        if ratio >= 1.25:
            tags.append("横版")
        elif ratio <= 0.8:
            tags.append("竖版")
        else:
            tags.append("方形")
        if width >= 1000 or height >= 720:
            tags.append("高清大图")
        if max(width, height) <= 240:
            tags.append("小尺寸图")
    return tags


def source_process_tags(source_type):
    mapping = {
        "manual-version-import": ["完整汇报导入", "手动导入"],
        "slide-control-import": ["单页拆分"],
        "control-resource-import": ["页面抽取"],
        "control-resource": ["页面抽取"],
        "template": ["手动导入"],
        "upload": ["自动扫描"],
        "auto": ["自动扫描"],
        "manual": ["手动导入"],
    }
    return mapping.get(source_type or "", [])


def page_usage_tags(text):
    probe = (text or "").lower()
    tags = []
    if any(word in probe for word in ["cover", "封面", "slide-01", "页码:01", "页面:01"]):
        tags.extend(["页面用途", "封面"])
    if any(word in probe for word in ["case", "案例", "客户"]):
        tags.extend(["页面用途", "案例页"])
    if any(word in probe for word in ["data", "metric", "指标", "图表", "map", "地图"]):
        tags.extend(["页面用途", "数据页"])
    if any(word in probe for word in ["end", "thanks", "结尾", "谢谢"]):
        tags.extend(["页面用途", "结尾页"])
    if any(word in probe for word in ["slide", "页码:", "content", "内容页"]):
        tags.extend(["页面用途", "内容页"])
    return tags


def resource_kind_for(path, media_kind, title="", tags="", *, image_module=None, image_sequence_module=None):
    if media_kind == "video":
        return "video"
    if media_kind == "gif":
        return "gif"
    text = " ".join([title or "", tags or "", path.name, path.as_posix()]).lower()
    basename = path.name.lower()
    logo_words = ("logo", "logotype", "brand", "mark", "商标", "品牌", "标志", "徽标")
    icon_words = ("icon", "icons", "favicon", "avatar", "badge", "图标", "头像", "按钮")
    if re.search(r"(^|[-_])icon([-_.]|$)", basename) or any(word in text for word in icon_words):
        return "icon"
    if any(word in text for word in logo_words):
        return "logo"
    if media_kind == "svg":
        return "icon"
    if media_kind == "image":
        traits = image_traits(path, image_module=image_module, image_sequence_module=image_sequence_module)
        width = traits.get("width") or 0
        height = traits.get("height") or 0
        has_alpha = traits.get("has_alpha")
        if width and height:
            max_side = max(width, height)
            min_side = min(width, height)
            ratio = max_side / min_side if min_side else 99
            if has_alpha and max_side <= 420 and ratio <= 4.5:
                return "logo" if ratio >= 2.1 else "icon"
            if max_side <= 160 and ratio <= 1.6:
                return "icon"
        return "image"
    return "other"


def asset_value(asset, key, default=""):
    try:
        value = asset[key]
    except (KeyError, IndexError, TypeError):
        value = default
    return value if value is not None else default


def suggest_material_tags(asset_or_text, resource_kind="", *, tag_rules=(), row_types=(sqlite3.Row, dict)):
    if isinstance(asset_or_text, row_types):
        identity_text = " ".join([
            asset_value(asset_or_text, "title"),
            asset_value(asset_or_text, "source_path"),
            asset_value(asset_or_text, "resource_kind"),
        ]).lower()
        text = " ".join([
            asset_value(asset_or_text, "title"),
            asset_value(asset_or_text, "usage"),
            asset_value(asset_or_text, "tags"),
            asset_value(asset_or_text, "source_path"),
            asset_value(asset_or_text, "media_kind"),
            asset_value(asset_or_text, "resource_kind"),
        ]).lower()
        kind = asset_value(asset_or_text, "resource_kind") or resource_kind
    else:
        text = str(asset_or_text or "").lower()
        identity_text = text
        kind = resource_kind

    tags = []

    def add(*values):
        tags.extend(values)

    if kind in {"image", "logo", "icon"}:
        add("图片素材")
    if kind == "video":
        add("视频素材", "可直接使用")
    if kind == "gif":
        add("GIF素材", "可直接使用")
    if kind == "svg":
        add("SVG素材")

    if kind == "logo" or any(word in identity_text for word in ["logo", "品牌", "商标", "标识", "mark"]):
        add("企业logo", "可直接使用")
        if any(word in identity_text for word in ["飞书", "feishu", "lark"]):
            add("飞书logo")
        elif any(word in identity_text for word in ["partner", "合作伙伴", "slack", "google", "amazon", "netflix", "skype", "dingtalk"]):
            add("合作伙伴logo")
        elif any(word in identity_text for word in ["客户", "米飞泰克斯", "client", "customer"]):
            add("客户logo")
        else:
            add("品牌标识")

    if kind == "icon" or any(word in identity_text for word in ["icon", "图标", "产品"]):
        add("产品icon", "可直接使用")
        if any(word in identity_text for word in ["飞书", "feishu", "lark"]):
            add("飞书产品")
        if any(word in identity_text for word in ["slack", "google", "amazon", "netflix", "skype", "dingtalk", "第三方"]):
            add("第三方产品")
        if any(word in identity_text for word in ["ai", "aily", "智能", "机器人", "agent"]):
            add("AI产品")
        if any(word in identity_text for word in ["管理", "admin", "组织", "权限"]):
            add("管理工具")
        if any(word in identity_text for word in ["协作", "办公", "lark", "feishu", "slack", "mail", "doc", "sheet"]):
            add("协作工具")

    if any(word in text for word in ["background", "bg", "cover", "section", "背景", "封面", "内容页", "dark", "tech", "科技"]):
        add("页面背景")
        if any(word in text for word in ["cover", "封面"]):
            add("封面背景")
        if any(word in text for word in ["content", "section", "内容页"]):
            add("内容页背景")
        if any(word in text for word in ["dark", "tech", "科技", "深色"]):
            add("深色科技风")

    if any(word in text for word in ["avatar", "portrait", "人物", "头像", "employee", "digital_employee"]):
        add("人物/头像")
        if any(word in text for word in ["digital", "数字人"]):
            add("数字人")

    if any(word in text for word in ["chart", "map", "timeline", "matrix", "bar", "柱状", "地图", "时间轴", "矩阵", "数据图表"]):
        add("数据图表")
        if any(word in text for word in ["map", "地图"]):
            add("地图")
        if any(word in text for word in ["bar", "柱状"]):
            add("柱状图")
        if any(word in text for word in ["timeline", "时间轴"]):
            add("时间轴")
        if any(word in text for word in ["matrix", "矩阵"]):
            add("矩阵图")

    if kind not in {"logo", "icon"} and any(word in text for word in ["reference", "参考", "screenshot", "截图", "mock", "demo", "dashboard", "screen", "界面", "控制台"]):
        add("参考截图")
        if any(word in text for word in ["dashboard", "screen", "界面", "控制台", "demo"]):
            add("产品截图", "页面截图")
        if any(word in text for word in ["design", "设计", "reference", "参考"]):
            add("设计参考")
        if any(word in text for word in ["reference", "参考"]):
            add("不可直接使用")
        else:
            add("仅作参考")

    if any(word in text for word in ["ai方案", "效率工程", "组织管理", "业务提效", "办公协同", "方案", "效率", "组织", "业务", "办公"]):
        add("方案素材")
        if "ai" in text or "智能" in text:
            add("AI方案")
        if "效率" in text:
            add("效率工程")
        if "组织" in text:
            add("组织管理")
        if "业务" in text:
            add("业务提效")
        if "办公" in text or "协同" in text:
            add("办公协同")

    for label, keywords in tag_rules:
        if any(keyword.lower() in text for keyword in keywords):
            add(label)
    add(*page_usage_tags(text))
    return merge_tags(tags)


def extract_company_logo_name(title="", source_path="", tags="", usage="", *, logo_title_by_source=None, company_name_rules=()):
    logo_title_by_source = logo_title_by_source or {}
    normalized_source = (source_path or "").replace("\\", "/")
    if normalized_source in logo_title_by_source:
        return logo_title_by_source[normalized_source]
    number_match = re.search(r"(?:^|/)(?:s\d+[-_])?logo[-_ ]?(\d+)\.(?:png|jpe?g|webp|svg)$", normalized_source, re.IGNORECASE)
    if number_match:
        mapped = logo_title_by_source.get(f"ppt-media/image{number_match.group(1)}.png")
        if mapped:
            return mapped
    text = " ".join([title or "", normalized_source]).lower()
    for keywords, company_name, subtag in company_name_rules:
        if any(keyword.lower() in text for keyword in keywords):
            return company_name, subtag
    return "", ""


def generic_logo_title(title="", source_path="", tags="", usage=""):
    text = " ".join([title or "", source_path or "", tags or "", usage or ""]).lower()
    normalized_source = (source_path or "").replace("\\", "/")
    number_match = re.search(r"(?:^|/)s(\d+)[-_]logo[-_ ]?(\d+)\.(?:png|jpe?g|webp|svg)$", normalized_source, re.IGNORECASE)
    if number_match:
        page_no, logo_no = number_match.groups()
        if page_no == "6":
            return f"先进制造企业标识 {logo_no}"
        if page_no == "9":
            return f"制造业场景标识 {logo_no}"
        return f"企业标识 {logo_no}"
    if "feishu" in text or "飞书" in text or "lark" in text:
        return "飞书"
    return "品牌标识"


def is_generic_logo_title(title):
    probe = (title or "").strip().lower()
    if not probe:
        return True
    if re.fullmatch(r"image\d+", probe):
        return True
    if re.fullmatch(r"[a-f0-9]{8,12}[-_ ].*", probe):
        return True
    return any(word in probe for word in [" logo", "logo ", "mark", "品牌标识"])


def apply_company_logo_metadata(
    title,
    tags,
    source_path="",
    usage="",
    resource_kind="",
    *,
    logo_title_by_source=None,
    company_name_rules=(),
):
    logo_title_by_source = logo_title_by_source or {}
    if resource_kind and resource_kind != "logo":
        return title, tags
    company_name, subtag = extract_company_logo_name(
        title,
        source_path,
        tags,
        usage,
        logo_title_by_source=logo_title_by_source,
        company_name_rules=company_name_rules,
    )
    source_key = (source_path or "").replace("\\", "/")
    if not company_name:
        if resource_kind == "logo" and is_generic_logo_title(title):
            company_name, subtag = generic_logo_title(title, source_path, tags, usage), "品牌标识"
        else:
            return title, tags
    cleaned = [
        tag
        for tag in split_tags(tags)
        if tag != "界面参考" and not (tag == "飞书logo" and subtag != "飞书logo")
    ]
    merged_tags = merge_tags(cleaned, ["企业logo", subtag])
    new_title = company_name if resource_kind == "logo" and (source_key in logo_title_by_source or is_generic_logo_title(title)) else title
    return new_title, ",".join(merged_tags)
