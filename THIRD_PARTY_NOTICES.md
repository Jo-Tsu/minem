# 第三方软件声明 / Third-Party Notices

MineM 依据 Apache-2.0 发行，并使用若干依据各自许可证发布的第三方软件。
本文仅用于说明，不能替代各项目随软件发布的原始许可证文本。

MineM is distributed under Apache-2.0 and uses third-party software under
their respective licenses. This file is informational and does not replace
the original license texts shipped by those projects.

## Web 与构建依赖 / Web and build dependencies

| Project | License |
| --- | --- |
| React / React DOM | MIT |
| Vite | MIT |
| TypeScript | Apache-2.0 |
| Lucide React | ISC |
| kokoro-js | Apache-2.0 |

## Python 依赖 / Python dependencies

| Project | License |
| --- | --- |
| Pillow | MIT-CMU |
| pypdf | BSD-3-Clause |

## 可选本地语音服务 / Optional local speech service

| Project | License |
| --- | --- |
| sherpa-onnx | Apache-2.0 |
| python-soundfile | BSD-3-Clause |
| edge-tts | LGPL-3.0, except `srt_composer.py` under MIT |

## 桌面客户端 / Desktop client

| Project | License |
| --- | --- |
| Tauri | Apache-2.0 OR MIT |
| Rust `url` crate | Apache-2.0 OR MIT |

MineM 不在源码仓库中再分发语音或 AI 模型权重。模型文件必须单独获取，并继续
受其模型卡和数据集许可证约束。

MineM does not redistribute speech or AI model weights in the source
repository. Model files must be obtained separately and remain subject to
their own model-card and dataset licenses.

发布二进制版本或容器镜像前，必须重新生成完整的软件物料清单，确保传递依赖和
随附许可证与实际发行产物一致。

Before publishing a binary release or container image, regenerate a complete
software bill of materials so transitive dependencies and bundled licenses
match the actual release artifact.
