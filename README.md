# cfst-ip-select

一个可复用的 Codex 技能及独立脚本：用内置 CFST 初筛 Cloudflare IPv4，再用 curl 对你指定的域名及 HTTPS 端口重复验证。域名和端口无默认值；不包含个人节点配置。

## 支持平台

内置官方 CFST v2.3.5：Windows x64/ARM64、macOS Intel/Apple Silicon、Linux x64/ARM64。其他 CPU 架构暂不支持。平台程序均原样来自官方发布，来源和 SHA256 见 `third_party/manifest.json`。不是每次运行都下载工具。

需要 Python 3.9+ 和 curl。Windows/macOS 通常提供 curl；Linux 如缺失请用系统包管理器安装。CFST 的 macOS 最低系统要求以官方 v2.3.5 发布说明为准；此包不包含 `_old` 兼容版本。不要为运行工具关闭系统安全机制。

本次发布在 Windows x64 上做了程序启动检查，并通过模拟 CFST/curl 的完整流程测试；六个平台均校验了官方归档摘要和程序架构。macOS、Linux 及 Windows ARM64 未在对应原生系统实机运行。

## 使用

把整个 `cfst-ip-select` 文件夹放到 Codex 的 skills 目录后，可请求：

> 使用 $cfst-ip-select 优选 Cloudflare IP，先询问我的域名、端口和测试网络。

也可在普通终端直接运行（先切到此技能目录）：

```sh
# Windows
python scripts/select_ip.py
# macOS / Linux
python3 scripts/select_ip.py
```

交互输入域名和端口。自动化调用时必须明确传入 `--domain` 和 `--port`，不会采用任何预置目标。输出路径应在技能目录之外，例如 `--output ../cfst-results`；目录必须尚不存在。没有指定输出目录时会在当前工作目录创建带时间戳的目录；如果从技能目录内部运行，则保存到用户主目录下，避免把运行数据混进公开包。

便捷入口：Windows 可双击 `run.cmd`；macOS/Linux 在终端运行 `sh run.sh`。这两个入口调用同一脚本，不需要手动选择 CFST 架构。

```sh
python3 scripts/select_ip.py --domain YOUR_DOMAIN --port YOUR_PORT --output ../cfst-results
python3 scripts/select_ip.py --check
python3 scripts/select_ip.py --help
```

`YOUR_DOMAIN`、`YOUR_PORT` 是需替换的说明占位符。`--input-csv` 可复用已有 CFST 结果；`--ip-file` 可指定自己的 IPv4 列表；默认复核 12 个候选，每个 5 次。上次结果不会被覆盖。

结果文件：`tcp.csv`、`cfst.log`（新初筛时）、`verified.csv`、`report.json`。报告只保存必要的耗时、状态和机房信息，不保存 trace 中客户端公网 IP。运行结果可能包含你输入的域名，不要将它们一起公开。

退出码：0 有全部复核通过的候选；2 无合格候选或命令行输入有误（看终端说明）；1 执行失败；130 用户取消。脚本不会修改 hosts、Clash 或 DNS，也不会创建定时任务。

## 单独执行 curl 测试

已有候选 IP 时，无需重新运行 CFST。在此技能目录运行以下命令，将占位内容替换为你自己的值：

```sh
python scripts/test_curl.py --domain YOUR_DOMAIN --port YOUR_PORT --ip YOUR_CANDIDATE_IP
```

macOS/Linux 使用 `python3`。默认复测 5 次，`--attempts 10` 可改为 10 次；目标域名、端口、IP 均无默认值。输出每次状态、耗时和机房。所有请求通过退出 0；存在失败退出 2；执行错误退出 1；取消退出 130。脚本不保存 trace 原文或修改任何网络配置。

## 测试含义

在需要使用的网络上直连测试，避免 TUN/VPN 接管；脚本只绕过 curl 的应用层代理。TCP 初筛不测带宽；HTTPS 测的是 `/cdn-cgi/trace` 边缘响应。通过不代表实际代理协议、回源或长期速度已验证。机房代码仅记录本次观察，不能作为永久路由承诺。

默认要求 5/5 HTTPS 成功；这只是有限样本。没有候选就保留原配置，不会把失败结果当作成功替换。切换网络后需要重新评估。

## 开发与分发

```sh
python3 -m unittest discover -s tests -v
python3 scripts/vendor_cfst.py
```

维护脚本重新获取固定版本六种官方程序，验证官方发布 SHA256，并附带对应源码归档和许可证。整个文件夹一起分发，勿遗漏 `third_party`。不把 CFST 二进制宣称为本项目原创；见 `THIRD_PARTY.md`。本项目新增代码以 GPL-3.0-only 发布。

参考：[CFST 官方仓库](https://github.com/XIU2/CloudflareSpeedTest)、[v2.3.5 发布](https://github.com/XIU2/CloudflareSpeedTest/releases/tag/v2.3.5)。
