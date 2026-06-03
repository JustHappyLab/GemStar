# GemStar 飞书接入指南

GemStar 使用飞书自定义机器人发送交易提醒。这个接入方式适合个人或小团队：配置简单，不需要完整的企业自建应用，也不影响本地 `alerts/live.jsonl` 和 `artifacts/current/trade_status.md/json` 状态记录。

## 1. 获取飞书 Webhook Token

GemStar 使用的是“飞书群自定义机器人”。你需要从机器人配置页拿到 Webhook 地址，地址最后一段就是 token。

操作步骤：

1. 打开飞书客户端，进入你想接收 GemStar 提醒的群。
2. 点击右上角群设置。
3. 找到“机器人”或“群机器人”入口。
4. 点击“添加机器人”。
5. 选择“自定义机器人”。
6. 填写机器人名称，例如 `GemStar`。
7. 添加成功后，飞书会显示一个 Webhook 地址，格式类似：

```text
https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

这里的：

```text
xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

就是飞书机器人的 token。GemStar 不需要你单独拆出 token，直接把完整 Webhook 地址填到 `FEISHU_WEBHOOK_URL`。

例如：

```bash
FEISHU_WEBHOOK_URL="https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

## 2. 获取签名密钥 Secret

飞书自定义机器人可以配置安全策略。建议开启“签名校验”，这样别人即使拿到群信息，也不能随便向你的群推消息。

在自定义机器人设置页里：

1. 找到“安全设置”。
2. 选择“签名校验”。
3. 飞书会生成一段签名密钥，通常以 `SEC` 开头。
4. 复制这段密钥，填入 `FEISHU_WEBHOOK_SECRET`。

例如：

```bash
FEISHU_WEBHOOK_SECRET="SECxxxxxxxxxxxxxxxxxxxxxxxx"
```

如果你没有开启签名校验，可以不配置 `FEISHU_WEBHOOK_SECRET`。但生产使用建议开启。

## 3. 配置环境变量

在项目根目录 `.env` 中添加：

```bash
FEISHU_WEBHOOK_URL="https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
FEISHU_WEBHOOK_SECRET="SECxxxxxxxxxxxxxxxxxxxxxxxx"
```

如果你没有开启签名校验，可以省略 `FEISHU_WEBHOOK_SECRET`。

## 4. 测试 Webhook

如果没有开启签名校验，可以用 `curl` 直接测试：

```bash
curl -X POST "${FEISHU_WEBHOOK_URL}" \
  -H "Content-Type: application/json" \
  -d '{
    "msg_type": "text",
    "content": {
      "text": "GemStar 飞书通知测试"
    }
  }'
```

如果开启了签名校验，建议直接用 GemStar 测试，因为 GemStar 会自动生成飞书要求的 `timestamp` 和 `sign`：

```bash
uv run gemstar trade --once --max-cycles 1
```

收到飞书消息后，说明 `FEISHU_WEBHOOK_URL` 和 `FEISHU_WEBHOOK_SECRET` 配置正确。

## 5. 运行 GemStar

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

飞书只负责主动提醒；本地文件是事实底稿，适合给第三方 skill、脚本或后续 dashboard 读取。

## 6. 推送内容

飞书消息会包含：

- 告警级别
- 标题
- 生成时间
- 交易建议正文
- 标的代码和名称
- 决策 ID

如果没有配置 `FEISHU_WEBHOOK_URL`，GemStar 不会报错，只会使用本地 JSONL 和状态文件。

## 7. 常见问题

**没有收到飞书消息**

先确认 `.env` 已被加载，`FEISHU_WEBHOOK_URL` 是完整的 `https://open.feishu.cn/open-apis/bot/v2/hook/...` 地址。注意不要只填最后一段 token，要填完整 URL。开启签名校验时，`FEISHU_WEBHOOK_SECRET` 必须与飞书后台显示的密钥一致。

**token 填哪一段？**

不用单独填 token。把飞书显示的完整 Webhook 地址填到 `FEISHU_WEBHOOK_URL`。地址最后一段 `hook/` 后面的 UUID 就是 token，但 GemStar 直接使用完整 URL。

**Secret 是不是 token？**

不是。token 是 Webhook URL 的一部分；secret 是安全设置里“签名校验”生成的密钥，通常以 `SEC` 开头。

**飞书收到消息，但状态不够详细**

飞书消息是轻量提醒。完整持仓、目标持仓、差额、浮盈亏和风险标记在：

```text
artifacts/current/trade_status.md
artifacts/current/trade_status.json
```

**想做按钮确认成交**

当前版本使用自定义机器人 Webhook，只做推送。按钮、回调、确认成交需要升级为飞书企业自建应用机器人，并接入事件订阅和卡片回调。
