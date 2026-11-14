# 私有云端部署

## 1. 创建自己的私有副本

在 GitHub 新建一个空的 **Private** 仓库。下载本项目源代码并推送到该仓库即可，默认分支使用 `main`。不要把原有私人部署仓库切换成公开仓库。

这个项目的邮件投递会把 `.delivery-state.json` 写进部署仓库，用于跨运行去重。程序会查询 GitHub 确认仓库为 private，公开仓库只用于预览和开发。

## 2. 配置 GitHub Actions

在私有仓库 Settings → Secrets and variables → Actions 中添加：

| 类型 | 名称 | 值 |
| --- | --- | --- |
| Secret | `QQ_EMAIL` | 自己的 QQ 邮箱地址，用于自发自收 |
| Secret | `QQ_SMTP_AUTH_CODE` | QQ 邮箱 SMTP 授权码，非登录密码 |
| Variable | `ENABLE_DELIVERY` | `true` |

先在 QQ 邮箱开启 SMTP 服务并取得授权码。所有凭据仅填入 Secrets，不能写入配置文件或 Issue。工作流使用自动生成的 `GITHUB_TOKEN` 写入私有投递记录；如果账号或组织限制 Actions 写权限，需要允许该工作流的 `contents: write`。

在 Actions → Financial news digest → Run workflow 中，先保持 `preview=true` 检查报告。需要验证真实邮件时，在目标时间后的 3 小时内将 `preview` 取消勾选；这会发送当前应发时段的一封邮件。此前已成功发送同一时段则跳过。

## 3. 定时与结果判断

仓库提供 UTC `02:07、02:17、02:47、12:07、12:17、12:47` 的补偿触发，对应北京时间／新加坡时间的早上 10 点和晚上 8 点时段。重复运行共用一个时段键。GitHub cron 可能排队、延迟或漏触发，不保证准点送达；公开仓库的长期不活动还可能停用定时器，因此邮件使用私有部署。

需要目标时段准时触发时，可以由自己已有的独立定时器，在 UTC `02:00`、`12:00` 调用 GitHub Actions 的 workflow dispatch API，使用 `financial-digest.yml`、`ref: main`、`inputs: {"trigger_source":"external_timer","preview":false}`。令牌应只授权到自己的部署仓库并具有 Actions 写入权限，保存在调度服务的秘密存储中。

可选 Secret `DIGEST_CONTROL_URL` 与 `DIGEST_CONTROL_KEY` 用于向自己的独立调度服务回传结果。两个都不设置时不回调；启用回调时端点需要接受 JSON POST，并对成功记录返回 HTTP 200：

```json
{"action":"ack","slot":"2026-01-01T10:00:00+08:00","status":"sent","accepted_at":"2026-01-01T02:00:30+00:00","run_id":"123456"}
```

认证使用 `Authorization: Bearer <DIGEST_CONTROL_KEY>`。`sending`、`uncertain` 表示投递结果不明确，应停止自动重复发送并提示人工核对。`no_updates` 表示本时段没有新增内容，正常完成且不发邮件；接收方和定时器应把它作为本时段的终态。`accepted_at` 可能为空。项目只提供回调客户端，独立定时器及回调接收端需要自行部署，不包含维护者的服务器配置。

检查 `output/run-status.json` 或运行日志：

| 状态 | 含义 |
| --- | --- |
| `preview` | 仅生成报告，未发邮件 |
| `sent` | SMTP 服务器已接受，不等于确认进了收件箱 |
| `sent` + `skipped: true` | 此时段已接受，未重复发信 |
| `failed` | 工作失败，需检查失败步骤和来源状态 |
| `no_updates` | 本时段只有已发送过的内容，正常完成且未发送邮件 |
| `sending` / `uncertain` | SMTP 或记录结果不明确，先核对邮箱，不能盲目重试 |

不要删除 `.delivery-state.json` 来强制重发。超过当前时段 3 小时且未成功发送，会报告错过窗口；有新鲜新闻不足、SMTP 拒绝、网络失败等情况时不会假报成功。云端运行不需要本机开机。

摘要和诊断报告以 Actions artifacts 保留 14 天，日志与文件可能包含新闻文本；私人部署仓库及输出均保持私有。用户添加的新闻源条款、云服务配额和账单由部署者自行管理。
