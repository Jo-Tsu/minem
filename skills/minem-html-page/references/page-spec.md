# MineM HTML Page Specification

The input is one UTF-8 JSON object.

## Fields

| Field | Required | Type | Notes |
| --- | --- | --- | --- |
| `title` | yes | string | The page's literal conclusion or subject. |
| `eyebrow` | no | string | Short section or context label. |
| `subtitle` | no | string | One supporting sentence. |
| `body` | no | string or string array | Up to four short paragraphs. |
| `bullets` | no | string array | Up to six points. |
| `metrics` | no | object array | Up to four `{ "value", "label" }` items. |
| `image` | no | string | Local path relative to the JSON file, or an absolute local path. |
| `imageAlt` | no | string | Meaningful image description. |
| `source` | no | string | Source note shown in the footer. |
| `footer` | no | string | Overrides the source note in the footer. |
| `layout` | no | string | `split`, `statement`, or `metrics`; default `split`. |
| `theme` | no | string | `dark` or `light`; default `dark`. |
| `accent` | no | string | Six-digit hex color, for example `#1687FF`. |

## Example

```json
{
  "eyebrow": "客户价值",
  "title": "统一素材链路，让汇报更新从小时缩短到分钟",
  "subtitle": "AI 负责理解与创作，MineM 负责页面生成、版本和汇报编排。",
  "bullets": [
    "外部资料生成标准页面素材",
    "页面编号、版本和来源统一管理",
    "插入或替换后保留原页面"
  ],
  "metrics": [
    {"value": "30×", "label": "默认滚动加载批次"},
    {"value": "1 条", "label": "从生成到发布的正式链路"}
  ],
  "image": "./workflow.png",
  "imageAlt": "MineM 素材生成与编排流程",
  "source": "MineM 产品能力",
  "layout": "split",
  "theme": "dark",
  "accent": "#28C7D9"
}
```

## Content Limits

- Prefer a title under 32 Chinese characters.
- Use no more than one subtitle, six bullets, and four metrics.
- If content exceeds one page, create multiple specifications and publish each page separately.
- Use `statement` for one strong message, `metrics` for quantified outcomes, and `split` for mixed text and imagery.
