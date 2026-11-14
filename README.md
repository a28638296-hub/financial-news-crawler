# 金融重点爬虫 · Financial News Crawler

[![Tests](https://github.com/a28638296-hub/financial-news-crawler/actions/workflows/tests.yml/badge.svg)](https://github.com/a28638296-hub/financial-news-crawler/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

采集公开财经快讯与 RSS，生成“发生了什么 → 可能影响 → 接下来关注什么”的中文金融简报。适合跟踪宏观经济、央行、利率、汇率、能源与重大政策。

**不需要付费 AI API。默认生成本地预览；邮件为可选功能。**

## 能做什么

- 预配置 13 个来源，包括新浪财经、华尔街见闻、美联储、BEA、欧洲央行及财经媒体 RSS。
- 只选过去 24 小时、有明确发布时间的新闻；更新时间、未知日期和未来日期不会充当新发布新闻。
- 按金融重要性、来源标记、时效与报道覆盖排序，最多整理 6 条重点；不是全网热搜榜。
- 合并格式和快讯前缀差异，保留不同国家、发言人、数字、方向等事实变化。
- 每个来源独立处理失败；坏条目单独跳过并记录原因类别、数量与耗时。
- 保存正文、HTML、来源证据及运行状态。邮件为无链接、无附件的中文纯文本。
- 可选 GitHub Actions + QQ 邮箱自发自收，按时段去重，投递结果不明确时停止自动重发。
- 跨次发送记录保留最近 30 天已发事实，筛选下一期前剔除重复内容；原事件只保留未发过的补充信息。没有新增重点时跳过邮件。

摘要采用**中文新闻摘录与规则分析**，不会自动把全部英文 RSS 翻译成中文，也不是大模型深度研报。英文来源会保留在证据文件中。来源中断、分页上限、周末新闻不足时可能少于 6 条；没有新鲜重点时退出失败，不用旧闻填充。

跨次去重使用文章标识、规范化标题、文章版本和事实句，不是任意同义改写的语义识别模型。只记录入选邮件的事件及其当时版本，未入选候选不会提前标为已读；未更新的旧文章不会换一段再次推送。已明确拒收的内容可以重试，投递结果不确定的内容会暂缓再次发送。普通本地预览不读取个人投递历史；可用 `--history-file sent-history.json` 做只读回放。

## 快速开始

需要 Python 3.12 或更新版本，以及能连接所配置新闻来源的网络。

```bash
git clone https://github.com/a28638296-hub/financial-news-crawler.git
cd financial-news-crawler
python -m venv .venv
```

Windows PowerShell：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe cloud_run.py --preview
```

Linux / macOS：

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python cloud_run.py --preview
```

打开 `output/最新金融总结.html` 或 `output/最新金融重点.txt`。`output/run-status.json` 中 `status: preview`、`sent: false` 表示没有发送邮件。

## 自定义来源与输出

复制 `finance_config.json` 后修改，保留 `mode: financial_news` 和空的 `watchlist`。

```bash
python cloud_run.py --preview --config my-config.json --output my-report
```

| 配置项 | 作用 |
| --- | --- |
| `request_timeout` | 单次请求读取超时秒数，1–30，默认 8 |
| `max_workers` | 并发来源数，1–8，默认 3 |
| `feeds[].enabled` | 是否启用来源 |
| `feeds[].id` | 唯一标识，只含字母、数字、下划线或连字符 |
| `feeds[].url` | 公开 HTTP(S) 来源，不放账号密码 |
| `feeds[].format` | `rss`（默认）、`sina_live` 或 `wallstreetcn` |
| `feeds[].max_pages` | 快讯分页上限，1–8，默认 8 |
| `network.allow_proxy_fallback` | 是否允许回退到本机已有的可用代理，默认关闭 |

默认优先直接联网，不修改系统网络设置；不同网络环境的可达来源可能不同。只添加有权访问的公开信息源，遵守来源使用条款、robots 规则和请求限制，不绕过登录、付费或访问控制。新增 RSS 需要 `id`、`name`、`kind`、`url` 四项。

## 云端预览与定时邮件

本仓库的 **Financial news digest** 工作流可手动运行，默认 `preview=true`，无需邮箱密钥。预览报告保留 14 天。公开仓库的 Actions 日志与报告可能公开，不上传私人配置。

要每天发送邮件，先创建自己的**私有部署仓库**并把源代码推送过去，再按 [云端部署说明](docs/cloud.md) 配置。公开仓库禁止写入邮件投递账本；私人邮箱、授权码、历史记录和调度服务配置不属于开源发布内容。

默认目标时段为北京时间／新加坡时间 **10:00、20:00**。GitHub 定时器可能延迟；需要更稳定的触发时可接入独立调度服务。只有云端部署运行时，才不依赖本机开机。代码不创建收费资源。

## 开发与验证

```bash
python -m unittest discover -p "test_*.py"
```

测试使用模拟网络与邮件，不需要个人密钥，不发送真实邮件。CI 验证 Linux Python 3.12 / 3.14 和 Windows Python 3.12。

主要模块：`finance_feeds.py` 采集，`finance_focus.py` 选择和去重，`finance_brief.py` 中文摘录与规则解释，`digest_config.py` 配置验证，`cloud_run.py` 命令行、报告及投递。部分底层模块保留历史研究接口兼容性，当前入口固定为金融新闻模式，不生成证券推荐。

## 许可证与数据

项目代码使用 [MIT License](LICENSE)，依赖保留各自许可证。新闻内容的版权属于原作者或发布机构；MIT 许可不覆盖采集到的第三方内容。本仓库不分发真实新闻语料、私人运行日志或凭据。参与开发见 [CONTRIBUTING.md](CONTRIBUTING.md)，变更见 [CHANGELOG.md](CHANGELOG.md)。
