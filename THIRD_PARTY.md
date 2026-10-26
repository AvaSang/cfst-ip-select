# 第三方组件

本项目内置 XIU2/CloudflareSpeedTest v2.3.5 的未修改官方程序和 IPv4 输入列表。

- 上游：https://github.com/XIU2/CloudflareSpeedTest
- 发布：https://github.com/XIU2/CloudflareSpeedTest/releases/tag/v2.3.5
- 许可：GNU GPL version 3；完整原文见 `third_party/CloudflareSpeedTest-LICENSE`。
- 对应源码：`third_party/CloudflareSpeedTest-v2.3.5-source.tar.gz`，包含该标签源码、go.mod/go.sum 及上游构建工作流。构建方式及 Go 版本以归档中的工作流为准，依赖信息由 go.mod/go.sum 指定。
- 六种平台二进制、原始发布归档与源码的 SHA256 和下载地址记录于 `third_party/manifest.json`。源码摘要是下载后计算的来源记录，非独立上游签名；发布归档摘要与 GitHub 发布 API 提供的 SHA256 比较后才解包。

分发此技能时一并保留许可证、源码归档及来源清单。Python 包装脚本使用标准库，不分发 Python 或 curl。CFST 自身依赖及版权声明见对应源码；上游名称及作者权益归其原作者所有。
