# GemStar 飞书接入指南

GemStar 使用飞书自定义机器人发送交易提醒。这个接入方式适合个人或小团队：配置简单，不需要完整的企业自建应用，也不影响本地 `alerts/live.jsonl` 和 `artifacts/current/trade_status.md/json` 状态记录。

## 1. 创建飞书自定义机器人

1. 打开飞书群。
2. 进入群设置，选择“机器人”。
3. 添加“自定义机器人”。
4. 复制生成的 Webhook 地址，格式类似：

```text
https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

建议在机器人安全设置里开启“签名校验”，并复制签名密钥。

## 2. 配置环境变量

在项目根目录 `.env` 中添加：

```bash
FEISHU_WEBHOOK_URL="https://open.feishu.cn/open-apis/bot/v2/hook/你的token"
FEISHU_WEBHOOK_SECRET="你的签名密钥"
```

如果你没有开启签名校验，可以省略 `FEISHU_WEBHOOK_SECRET`。

## 3. 运行 GemStar

```bash
uv run gemstar trade --once
```

或长期运行：

```bash
uv run gemstar trade
```

每次运行都会同时写入：

```text
alerts/live.jsonl
artifacts/current/trade_status.json
artifacts/current/trade_status.md
```

飞书只负责主动提醒；本地文件是事实底稿，适合给 qclaw skill、脚本或后续 dashboard 读取。

## 4. 推送内容

飞书消息会包含：

- 告警级别
- 标题
- 生成时间
- 交易建议正文
- 标的代码和名称
- 决策 ID

如果没有配置 `FEISHU_WEBHOOK_URL`，GemStar 不会报错，只会使用本地 JSONL 和状态文件。

## 5. 常见问题

**没有收到飞书消息**

先确认 `.env` 已被加载，`FEISHU_WEBHOOK_URL` 是完整的 `https://open.feishu.cn/open-apis/bot/v2/hook/...` 地址。开启签名校验时，`FEISHU_WEBHOOK_SECRET` 必须与飞书后台显示的密钥一致。

**飞书收到消息，但状态不够详细**

飞书消息是轻量提醒。完整持仓、目标持仓、差额、浮盈亏和风险标记在：

```text
artifacts/current/trade_status.md
artifacts/current/trade_status.json
```

**想做按钮确认成交**

当前版本使用自定义机器人 Webhook，只做推送。按钮、回调、确认成交需要升级为飞书企业自建应用机器人，并接入事件订阅和卡片回调。
