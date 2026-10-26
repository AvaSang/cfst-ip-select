---
name: cfst-ip-select
description: 使用内置 CloudflareSpeedTest 初筛 IPv4，再用 curl 对用户指定的域名和 HTTPS 端口重复验证并排序。适用于 Cloudflare 入口 IP 优选和连通性排查，支持 Windows、macOS、Linux 的 x64/ARM64；不用于 WARP 优选。
---

# Cloudflare 入口 IP 优选

运行 `scripts/select_ip.py` 完成 TCP 初筛和 HTTPS 复核。内置 CFST v2.3.5 六个平台程序，自动识别平台；运行依赖 Python 3.9+ 和 curl，无额外 Python 包。

## 先取得输入

- 域名、HTTPS 端口没有默认值。使用用户明确提供的值；缺失时一起询问，不能套用历史用户的域名或端口。
- 确认测试的网络，例如校园网或手机热点。告知用户测试流量需直连；curl 的 `--noproxy` 不能绕过 TUN。不要擅自停止代理进程。
- 默认验证路径是 Cloudflare 提供的 `/cdn-cgi/trace`，验证的是到边缘的 HTTPS，不是源站、WebSocket/VLESS 或下载带宽。

## 单独测试已知 IP（不运行 CFST）

用户已经有候选 IP、只要求 curl 验证时，使用 `scripts/test_curl.py`。域名、HTTPS 端口和候选 IPv4 必须由用户提供，不设置目标默认值：

```text
python scripts/test_curl.py --domain <用户域名> --port <用户端口> --ip <候选IPv4>
```

macOS/Linux 通常把 `python` 换成 `python3`。默认复测 5 次，可用 `--attempts` 调整。该脚本只需要 Python 3.9+ 和 curl，不会启动 CFST、修改 hosts 或更改客户端配置。每次打印 HTTP 状态、总耗时、机房和错误分类；最后汇总成功次数及成功请求耗时中位数。复用 `select_ip.py` 中的 HTTPS 验证逻辑，分发时保留这两个脚本。

## 执行

以技能目录为当前目录，Windows 用 `python`，macOS/Linux 通常用 `python3`：

```text
python scripts/select_ip.py --domain <用户域名> --port <用户端口> --output <结果目录>
```

也可不带参数交互运行，输入域名和端口。占位内容不能原样执行。不要在无人值守环境省略输入。

脚本用 CFST 的 `-tp` 指定实际端口，默认 50 并发、每地址 4 次 TCP 测试、连接失败率上限 0、关闭下载测速。结果按延迟分段抽取最多 12 个候选（而非只取最快的一小段），每个候选串行 curl 复核 5 次。筛选窗口有 10 分钟上限，HTTPS 总复核次数有明确上限。

如用户已有一轮 CSV，可用 `--input-csv <文件>` 跳过初筛。候选必须是合法的公网 IPv4。工具帮助可用 `--help` 查看；`--check` 仅检查依赖及内置程序完整性，不发起测速。

若初筛为空，报告无候选；可在解释取舍后调整 `--max-loss 0.25` 再测一次，不无限重试。网络、系统、CFST 或 curl 失败必须与“没有好 IP”区分。不要因为错误就关闭证书校验。

## 解读与交付

- 报告目标、端口、测试时间、成功次数/总次数、成功请求耗时中位数和观察到的机房。结果保存在 `verified.csv`、`report.json` 及初筛 CSV/日志中。
- 默认只把全部 HTTPS 请求通过的候选列为可推荐候选；先按成功率，再按成功请求耗时中位数排序。只测一次快不能称为稳定。
- TCP 所谓“丢包率”是连接尝试失败比例；失败不等于直接测得的数据包丢失。
- 低 TCP 延迟的 IP 仍可能返回 HTTP 403/1034，须排除。CFST v2.3.5 HTTPing 的两秒超时可能造成误筛，因此本流程使用 curl 复核。
- 同 IP 不保证固定机房或长期速度。没有全通过候选就明确报告，不自动选用部分失败的地址。
- 脚本不会修改 hosts、DNS、Clash、订阅，也不建立定时任务。若用户另外要求应用结果，沿用其授权范围，并保留域名对应的 SNI 和 HTTP Host。
- 公开分发仅包含此技能目录的代码和内置工具，不携带用户输入或运行结果。结果默认写入工作目录的独立子目录。

平台和许可证说明见 [README.md](README.md)、[THIRD_PARTY.md](THIRD_PARTY.md)。维护内置版本时运行 `scripts/vendor_cfst.py`，它校验官方发布摘要并附带对应源码。
