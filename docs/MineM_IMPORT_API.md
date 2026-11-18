# MineM 导入接口

适用于当前本地 Docker 版 MineM，默认地址为 `http://127.0.0.1:8790`。文件和飞书链接共用异步任务模型。调用方提交后保存任务 ID，等任务完成，再验收汇报、页面和媒体。

## 1. 接口一览

| 方法与路径 | 用途 | 正常响应 |
| --- | --- | --- |
| `POST /api/import-tasks` | 上传一个 HTML、ZIP 或媒体文件 | `202` 和 `task`；同步命中历史批次时返回 `200` 和 `reused: true` |
| `POST /api/import-tasks/drive` | 提交 1–8 个飞书云空间文件夹链接 | `202` 和 `tasks[]` |
| `GET /api/import-tasks/{taskId}` | 按 ID 查询单个任务 | `200` 和 `task` |
| `GET /api/import-tasks` | 查询最近更新的任务 | `200` 和 `tasks[]`，最多 24 条 |
| `GET /api/reports/{assetId}/arrangement` | 查询汇报编排、页面入口和预览 | `200` 和 `pages[]` |
| `GET /api/reports/{assetId}/trusted-entry` | 查询汇报入口校验记录和页数 | 校验通过返回 `200` |

上传和任务查询的成功响应都包含 `ok: true`。错误响应通常为 `{"ok":false,"error":"原因"}`。任务查询返回 `ok: true` 表示查到了任务，导入结果由 `task.status` 决定。

## 2. 上传文件

使用 `multipart/form-data`，每次提交一个 `file`。可选的 `description` 用于记录本次导入说明。浏览器用 `FormData` 构造请求，由浏览器生成带 boundary 的 Content-Type。

```bash
BASE=http://127.0.0.1:8790
curl -sS "$BASE/api/import-tasks" \
  -F 'file=@./report.zip' \
  -F 'description=销售汇报'
```

支持 `.html`、`.htm`、`.zip`、`.svg`、`.png`、`.jpg`、`.jpeg`、`.gif`、`.webp`、`.mp4`、`.mov`、`.m4v`、`.webm`。单个 HTML 文件应自包含。HTML 需要本地图片、样式、脚本、字体或视频时，连同依赖一起打包成 ZIP，并保留相对路径。直接上传图片或视频可能产出 `resource` 素材，页面素材以 `control` 表示，完整汇报以 `report` 表示。

### 汇报 ZIP 的结构

推荐以根目录 `manifest.json` 声明正式入口和页面顺序。每页的 HTML 与播放依赖放在该页自己的目录中。两页使用同一张图时，各自在自己的目录保存一份原图。汇报按确认顺序播放页面素材，页面也可以单独打开。

```text
report.zip
├── manifest.json
├── index.html
└── pages/
    ├── page-001/
    │   ├── index.html
    │   └── assets/cover.png
    └── page-002/
        ├── index.html
        └── assets/demo.mp4
```

```json
{
  "asset_type": "report",
  "title": "销售汇报",
  "entry": "index.html",
  "pages": [
    {"display_page": 1, "title": "封面", "path": "pages/page-001/index.html"},
    {"display_page": 2, "title": "产品演示", "path": "pages/page-002/index.html"}
  ]
}
```

使用从 1 开始的唯一页码和独立路径。页面内使用 `assets/cover.png` 这类相对引用。把 `img`、SVG 的 `image href` 或 `xlink:href`、CSS 背景、视频与海报、子 iframe 的依赖一起打包。压缩包不得包含符号链接、绝对路径或越界路径。保持素材源布局和媒体原文件，避免将大图、视频反复内联进 HTML。

### 默认限制

| 项目 | 限制 |
| --- | --- |
| 上传文件 | 512 MiB |
| 请求总长（含 multipart 开销） | 528 MiB |
| ZIP 内普通文件 | 5,000 个 |
| ZIP 内单文件解压后 | 256 MiB |
| ZIP 解压后总大小 | 1 GiB |

限制可由部署配置调整。请求或上传文件超限会返回 HTTP `413`。ZIP 内容或依赖检查在后台执行，超限、解压失败和缺失依赖写入任务错误。

## 3. 添加飞书链接

每点一次「添加链接」就增加一个输入项，提交时组成一个 `links` 数组。浏览器从 MineM 同源页面提交。命令行传入 JSON 即可。

```bash
curl -sS "$BASE/api/import-tasks/drive" \
  -H 'Content-Type: application/json' \
  --data '{
    "links": [
      "https://example.feishu.cn/drive/folder/ExampleFolder123456",
      "https://example.feishu.cn/drive/folder/ExampleFolder789012"
    ],
    "description": "批量导入"
  }'
```

- 用有访问权限的真实链接替换示例。支持 `feishu.cn`、`larkoffice.com`、`larksuite.com` 及其租户子域的 HTTPS `/drive/folder/{token}` 链接。查询参数不参与去重。
- `links` 必填，为 1–8 项字符串。单条最多 2,048 字符，JSON 请求最多 24,000 字节。可选 `description` 最多保留 1,000 字符。
- 任意一条格式无效，整批返回 `400` 并指出条目。格式校验通过后，按文件夹 token 去重，保留第一次出现的顺序。每个不同文件夹返回一个任务，下载失败只影响对应任务。
- 本机需要登录 `lark-cli`，并在项目目录运行 `./scripts/start_drive_import_worker.sh`。本机重启后需重新运行。文件夹及其依赖文件的读取权限沿用该账号。
- 文件夹包含根目录 `index.html` 时，从这一入口处理。制作项目以 `output/index.html` 为入口时，仅抓取正式入口、播放依赖和可用的页索引。逐页检查封装后的播放资源，飞书妙搭公开字体会随对应页面保存。其余无法离线播放的资源会报告所在页和来源。
- 飞书链接入口接收兼容的飞书 Deck HTML 导出目录。飞书在线文档和在线幻灯片先导出为可独立播放的 HTML 或 ZIP，再走文件上传。
- 飞书链接在服务端逐页封装。下载和封装受素材包的文件数量及总大小限制，生成的 ZIP 在入库前通过统一的解压校验。HTTP 文件上传的大小限制适用于直接上传 HTML、ZIP 和资源文件。
- 下载中的 `message` 可能包含已接收的数据量。根目录镜像下载有约 30 分钟下载上限，约 2 分钟无传输进展后自动重试一次。制作项目分文件读取，也可能自动重试。批次中的任务依次处理，排队时长和资源体积都会影响完成时间。

## 4. 查询任务及重试

```bash
TASK_ID='替换为 POST 返回的 task.id 或 tasks[].id'
curl -sS "$BASE/api/import-tasks/$TASK_ID"
```

批量提交响应使用 `tasks` 数组，单文件提交和单任务查询使用 `task` 对象。以下为任务成功响应的部分字段。

```json
{
  "ok": true,
  "task": {
    "id": "task-20260101-093000-a1b2c3d4",
    "status": "success",
    "progress": 100,
    "message": "导入成功，可点击预览",
    "assetCount": 3,
    "assetId": "import-20260101-093000-c1d2e3f4-report",
    "assetType": "report",
    "previewUrl": "/reports/import-20260101-093000-c1d2e3f4-report/index.html",
    "error": ""
  }
}
```

| 字段 | 调用方用法 |
| --- | --- |
| `id` | 任务 ID，保存它用于轮询和排查 |
| `status` | `queued`、`running`、`success`、`failed` |
| `progress`、`message` | 显示阶段和进度；进度值不代表下载字节百分比 |
| `fileName`、`fileCount` | 导入显示名和系统记录的文件数 |
| `sourceUrl` | 飞书文件夹链接。保留租户域名与文件夹路径，省略查询参数和片段。直接上传和未记录链接的历史任务返回空字符串 |
| `assetCount`、`thumbnailCount` | 本次新增素材数和生成的缩略图数；历史复用时可能为 0 |
| `uploadId` | 导入批次 ID，成功时可能指向历史批次 |
| `assetId`、`assetCode`、`assetTitle`、`assetType` | 返回的入口素材信息；汇报接口使用 `assetId` |
| `previewUrl` | 预览相对地址，以 MineM 根地址补全 |
| `error` | 失败原因，用于定位缺失文件、权限或网络问题 |
| `createdAt`、`updatedAt` | Unix 毫秒时间戳 |

保存提交返回的所有任务 ID。每 2–3 秒按 ID 查询一次；遇到短暂网络错误，可逐步延长轮询间隔。收到 `success` 后进入验收，收到 `failed` 后停止轮询并显示 `error`。可以关闭页面或刷新后用原 ID 继续查询。飞书链接队列随项目运行目录保存，网页服务重启后按原任务 ID 继续处理。最近任务列表适合恢复界面，完整状态以单任务查询为准。

| 情况 | 调用方处理 |
| --- | --- |
| 提交 HTTP `400`、`413`、`415` | 修正文件、链接、体积或 Content-Type 后再提交 |
| 飞书提交 HTTP `403` | 从 MineM 同源页面提交，检查请求的 Origin |
| 飞书提交 HTTP `503` | 恢复本机飞书下载服务后再提交 |
| 查询 HTTP `404` | 确认任务 ID 及服务器地址 |
| 任务 `failed` | 缺依赖先补资源，权限错误先恢复访问，网络中断后重试。批量只重新提交实际失败的链接 |
| 提交连接中断，未拿到任务 ID | 先核对最近任务，再决定是否重传。内容去重可复用已入库素材，当前没有请求级幂等键 |
| 服务重启后任务长时间停在非终态 | 当前后台任务没有重启续跑能力。核对素材库，再重新提交未完成的导入；安排重启前尽量等运行中的任务完成 |

同一批次的重复链接只创建一个任务。已入库的相同内容可复用已有素材，重复请求仍可能新建任务记录。同步复用可能在上传响应里带 `reused: true`，后台复用通常通过成功任务的 `message` 和已有的 `assetId`、`uploadId` 体现。

## 5. 导入后验收

收到 `success` 后，确认 `assetId` 与 `previewUrl` 存在并能打开。汇报增加以下检查，其中 `REPORT_ID` 取任务的 `assetId`。

```bash
REPORT_ID='替换为任务返回的 assetId'
curl -sS "$BASE/api/reports/$REPORT_ID/trusted-entry"
curl -sS "$BASE/api/reports/$REPORT_ID/arrangement"
```

1. **汇报入口与页数**。入口能打开，`trusted-entry` 返回的 `pageCount` 与预期相符。在编排响应中按 `order` 检查播放顺序，`slotNumber` 是页槽编号，`hidden` 表示隐藏，页面 ID 应各不相同。
2. **封面和单页**。在汇报列表确认封面，在播放器打开首、中、末页，从 `pages[].previewUrl` 单独打开至少一个包含 SVG、图片或 iframe 的页面。`thumbnailUrl` 可用于检查静态缩略图；存在 `thumbnailFrameUrl` 时也可用页面预览封面。
3. **媒体与交互**。有视频时逐个点击播放，确认画面和时间轴前进；可拖动进度条时验证 seek。包含 iframe 或动态加载数据的页面，在浏览器逐项操作，确认相关资源请求正常，并检查图片样式和排版。
4. **资源归属**。对自建 ZIP 或导出的页面包核对，每页从自己的目录加载该页所需资源。对相同输入重复导入后，确认素材总数未因重复任务增加。

HTTP `200` 只证明入口可访问，静态依赖检查也无法单独证明浏览器动态加载、交互和媒体兼容性。接入验收应保留实际浏览器播放用例，尤其是含 SVG 内嵌图片或视频的页面。

## 6. 本次核对

本地隔离库验证了单 HTML 和两页 ZIP 入库、页面编排、重复复用，以及 SVG 图片缺失时的失败提示。正式库只读核对了已有 63 页飞书汇报的编排和第 23、50、58 页入口；此前已在浏览器播放过第 23、50 页视频并验证第 58 页图表。接入测试使用独立库，正式库用于只读验收。


## 2026-11-18 稳定性补充

- `GET /api/import-tasks` 与单任务查询保留 `sourceUrl`；网页“导入记录”可打开原飞书链接，并以原链接重试失败任务。历史未记录链接的任务不会伪造来源。
- 未提交素材的失败导入删除临时上传文件、解压目录和空上传记录；已提交素材不会因预览生成失败被删除。
- 扫描事务内只写素材和资源关系。缺失缩略图在提交后的阶段或首次读取时生成，避免占用数据库写锁。
- `GET /api/reports/{reportId}/exports` 返回最近的导出任务。关闭弹窗后，重新打开可恢复运行状态并下载已完成文件。
- 导出先检查完整资源依赖。PDF 额外等待字体、图片解码与页面渲染，失败包含页号；不能把响应成功或截图文件存在等同于内容验收通过。
