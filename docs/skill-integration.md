# GemStar Skill 安装指南

GemStar 自带一个对外集成 skill，可安装到 QClaw、Codex 或其他兼容 `SKILL.md` 协议的宿主里，用自然语言查询当前持仓、目标持仓、最新提醒、策略排行榜和运行状态。这个 skill 只读取本地状态和提醒文件，或在用户明确要求时触发一次 `gemstar trade --once --max-cycles 1`，不会执行真实下单。

## 1. Skill 位置

GemStar 仓库内置的对外 skill 位于：

```text
integrations/gemstar-skill/
```

里面包含：

```text
integrations/gemstar-skill/SKILL.md
integrations/gemstar-skill/scripts/gemstar-status.sh
integrations/gemstar-skill/scripts/gemstar-alerts.sh
```

`SKILL.md` 是兼容宿主读取的说明文件；两个脚本分别用于读取最新交易状态和最新提醒。

## 2. 找到宿主的 skills 目录

宿主需要能扫描到 `gemstar-skill` 这个目录。不同生态的 skills 目录不同，常见形式包括：

```text
~/.qclaw/skills
~/.codex/skills
/path/to/agent/skills
```

下面用通用环境变量表示你的目标安装目录：

```bash
export SKILL_HOST_SKILLS_DIR="$HOME/.qclaw/skills"
mkdir -p "$SKILL_HOST_SKILLS_DIR"
```

如果你使用的不是 QClaw，把 `SKILL_HOST_SKILLS_DIR` 改成对应宿主实际扫描的 skills 目录即可。查看宿主 README、启动配置或配置文件里的 `skills`、`skill_dir`、`tools` 等字段通常能找到。

## 3. 推荐安装：软链接

推荐用软链接安装。这样 GemStar 仓库里的 skill 更新后，宿主读取到的也是最新版。

```bash
cd /Users/ken/workspace/GemStar

export SKILL_HOST_SKILLS_DIR="$HOME/.qclaw/skills"
mkdir -p "$SKILL_HOST_SKILLS_DIR"

ln -sfn "$PWD/integrations/gemstar-skill" "$SKILL_HOST_SKILLS_DIR/gemstar-skill"
```

安装后检查：

```bash
ls -la "$SKILL_HOST_SKILLS_DIR/gemstar-skill"
cat "$SKILL_HOST_SKILLS_DIR/gemstar-skill/SKILL.md" | sed -n '1,20p'
```

## 4. 备选安装：复制

如果宿主运行环境不允许软链接，可以复制目录：

```bash
cd /Users/ken/workspace/GemStar

export SKILL_HOST_SKILLS_DIR="$HOME/.qclaw/skills"
mkdir -p "$SKILL_HOST_SKILLS_DIR"

rm -rf "$SKILL_HOST_SKILLS_DIR/gemstar-skill"
cp -R "$PWD/integrations/gemstar-skill" "$SKILL_HOST_SKILLS_DIR/gemstar-skill"
```

复制安装的缺点是：GemStar 更新 skill 后，需要重新复制一次。

## 5. 验证脚本可用

先在终端验证 skill 里的脚本能跑：

```bash
bash /Users/ken/workspace/GemStar/integrations/gemstar-skill/scripts/gemstar-status.sh
bash /Users/ken/workspace/GemStar/integrations/gemstar-skill/scripts/gemstar-alerts.sh 5
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

## 6. 在宿主中测试

重启宿主，或让宿主重新加载 skills。然后用类似问题测试：

```text
GemStar 当前持仓是什么？
GemStar 今天建议买卖什么？
GemStar 目标仓位和当前仓位差多少？
GemStar 最近 5 条提醒是什么？
GemStar 最新 leaderboard 是什么？
```

期望行为：

- 问当前持仓、目标持仓、调仓差额时，宿主优先读取 `artifacts/current/trade_status.json` 或 `trade_status.md`。
- 问最近提醒时，宿主读取 `alerts/live.jsonl` 或运行 `gemstar alerts latest`。
- 问运行状态时，宿主运行 `gemstar status`。
- 只有你明确说“现在刷新 GemStar”或“跑一次 GemStar”，宿主才可以执行 `gemstar trade --once --max-cycles 1`。

## 7. 安全边界

这个 skill 只允许查询和本地刷新，不允许实盘下单。

明确禁止：

- 调用券商、QMT、ptrade 或任何真实交易 API。
- 通过聊天宿主直接买入或卖出。
- 修改策略 YAML、因子池、`.env`、`gemstar.yaml` 等配置。
- 把 GemStar 的提醒包装成确定性投资建议。

如果用户要求“帮我买入/卖出”，skill 应拒绝执行，只能提示查看 GemStar 生成的建议和决策 ID。

## 8. 常见问题

**宿主没识别到 skill**

确认 `gemstar-skill` 目录在宿主实际扫描的 skills 目录下，并且目录内有 `SKILL.md`：

```bash
find "$SKILL_HOST_SKILLS_DIR/gemstar-skill" -maxdepth 2 -type f
```

**脚本提示找不到 GemStar**

当前脚本写死 GemStar 路径为：

```text
/Users/ken/workspace/GemStar
```

如果你把项目放到了别的位置，需要修改：

```text
integrations/gemstar-skill/SKILL.md
integrations/gemstar-skill/scripts/gemstar-status.sh
integrations/gemstar-skill/scripts/gemstar-alerts.sh
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
