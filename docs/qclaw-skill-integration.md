# GemStar QClaw Skill 安装指南

GemStar 自带一个 QClaw skill，用来在 QClaw/微信里查询当前持仓、目标持仓、最新提醒、策略排行榜和运行状态。Skill 只读取本地状态和提醒文件，或在用户明确要求时触发一次 `gemstar trade --once --max-cycles 1`，不会执行真实下单。

## 1. Skill 位置

GemStar 仓库内置 skill 目录：

```text
skills/gemstar-qclaw/
```

里面包含：

```text
skills/gemstar-qclaw/SKILL.md
skills/gemstar-qclaw/scripts/gemstar-status.sh
skills/gemstar-qclaw/scripts/gemstar-alerts.sh
```

`SKILL.md` 是 QClaw 读取的说明文件；两个脚本分别用于读取最新交易状态和最新提醒。

## 2. 找到 QClaw 的 skills 目录

QClaw 需要能扫描到 `gemstar-qclaw` 这个 skill 目录。不同安装方式的 skills 目录可能不同，常见位置包括：

```text
~/.qclaw/skills
~/qclaw/skills
/path/to/qclaw/skills
```

如果你的 QClaw 支持配置 skills 目录，建议明确设置为一个固定路径。下面示例用环境变量表示：

```bash
export QCLAW_SKILLS_DIR="$HOME/.qclaw/skills"
mkdir -p "$QCLAW_SKILLS_DIR"
```

如果你不确定 QClaw 的 skills 目录在哪里，先查看 QClaw 的启动配置、项目 README 或配置文件里是否有 `skills`、`skill_dir`、`tools` 之类字段。

## 3. 推荐安装：软链接

推荐用软链接安装。这样 GemStar 仓库里的 skill 更新后，QClaw 读取到的也是最新版。

```bash
cd /Users/ken/workspace/GemStar

export QCLAW_SKILLS_DIR="$HOME/.qclaw/skills"
mkdir -p "$QCLAW_SKILLS_DIR"

ln -sfn "$PWD/skills/gemstar-qclaw" "$QCLAW_SKILLS_DIR/gemstar-qclaw"
```

安装后检查：

```bash
ls -la "$QCLAW_SKILLS_DIR/gemstar-qclaw"
cat "$QCLAW_SKILLS_DIR/gemstar-qclaw/SKILL.md" | sed -n '1,20p'
```

## 4. 备选安装：复制

如果你的 QClaw 运行环境不允许软链接，可以复制目录：

```bash
cd /Users/ken/workspace/GemStar

export QCLAW_SKILLS_DIR="$HOME/.qclaw/skills"
mkdir -p "$QCLAW_SKILLS_DIR"

rm -rf "$QCLAW_SKILLS_DIR/gemstar-qclaw"
cp -R "$PWD/skills/gemstar-qclaw" "$QCLAW_SKILLS_DIR/gemstar-qclaw"
```

复制安装的缺点是：GemStar 更新 skill 后，需要重新复制一次。

## 5. 验证脚本可用

先在终端验证 skill 里的脚本能跑：

```bash
bash /Users/ken/workspace/GemStar/skills/gemstar-qclaw/scripts/gemstar-status.sh
bash /Users/ken/workspace/GemStar/skills/gemstar-qclaw/scripts/gemstar-alerts.sh 5
```

如果还没有运行过 `gemstar trade`，`gemstar-status.sh` 会提示：

```text
GemStar has not generated artifacts/current/trade_status.md yet.
Run: uv run python -m src.cli.app trade --once --max-cycles 1
```

这是正常的。先运行一次：

```bash
cd /Users/ken/workspace/GemStar
uv run gemstar trade --once --max-cycles 1
```

之后再运行 `gemstar-status.sh`，应该能看到 `artifacts/current/trade_status.md` 的内容。

## 6. 在 QClaw 中测试

重启 QClaw，或让 QClaw 重新加载 skills。然后用类似问题测试：

```text
GemStar 当前持仓是什么？
GemStar 今天建议买卖什么？
GemStar 目标仓位和当前仓位差多少？
GemStar 最近 5 条提醒是什么？
GemStar 最新 leaderboard 是什么？
```

期望行为：

- 问当前持仓、目标持仓、调仓差额时，QClaw 优先读取 `artifacts/current/trade_status.json` 或 `trade_status.md`。
- 问最近提醒时，QClaw 读取 `alerts/live.jsonl` 或运行 `gemstar alerts latest`。
- 问运行状态时，QClaw 运行 `gemstar status`。
- 只有你明确说“现在刷新 GemStar”或“跑一次 GemStar”，QClaw 才可以执行 `gemstar trade --once --max-cycles 1`。

## 7. 安全边界

这个 skill 只允许查询和本地刷新，不允许实盘下单。

明确禁止：

- 调用券商、QMT、ptrade 或任何真实交易 API。
- 通过微信直接买入或卖出。
- 修改策略 YAML、因子池、`.env`、`gemstar.yaml` 等配置。
- 把 GemStar 的提醒包装成确定性投资建议。

如果用户在 QClaw 里要求“帮我买入/卖出”，skill 应拒绝执行，只能提示查看 GemStar 生成的建议和决策 ID。

## 8. 常见问题

**QClaw 没识别到 skill**

确认 `gemstar-qclaw` 目录在 QClaw 实际扫描的 skills 目录下，并且目录内有 `SKILL.md`：

```bash
find "$QCLAW_SKILLS_DIR/gemstar-qclaw" -maxdepth 2 -type f
```

**脚本提示找不到 GemStar**

当前脚本写死 GemStar 路径为：

```text
/Users/ken/workspace/GemStar
```

如果你把项目放到了别的位置，需要修改：

```text
skills/gemstar-qclaw/SKILL.md
skills/gemstar-qclaw/scripts/gemstar-status.sh
skills/gemstar-qclaw/scripts/gemstar-alerts.sh
```

把里面的路径替换成你的 GemStar 绝对路径。

**没有当前持仓**

先确认 `gemstar trade` 至少运行过一次，并生成：

```text
artifacts/current/trade_status.md
artifacts/current/trade_status.json
```

也可以直接运行：

```bash
cd /Users/ken/workspace/GemStar
uv run gemstar trade --once --max-cycles 1
```
