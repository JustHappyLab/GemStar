# GemStar 优化 TODO

> 状态：LLM provider 已收敛为单一 `claude_code`。本轮目标是让测试、
> 文档和配置示例与当前实现一致，并保留 provider 字段作为未来扩展点。

## 已完成

- [x] 删除已过期的 LLM client 测试文件。
- [x] 重写 provider 测试，只覆盖 `base` 与 `ClaudeCodeProvider`。
- [x] 将 LLM stage 测试改为 `LLMGenerate` fake，不再依赖真实 SDK 或网络。
- [x] 更新 role registry、CLI config、CLI run、pipeline 相关测试断言。
- [x] 修正 live 通知测试，使其匹配当前中文标题与正文。
- [x] 隔离 trade smoke test，避免触发真实 Tushare 初始化或写入用户 home。
- [x] 同步 README、架构图、代码 docstring、配置模板里的 provider 描述。

## 决策记录

- `LLMConfig.provider`、`RoleOverride.provider`、`EngineeringConfig.provider`
  暂时保留，当前类型收窄为 `Literal["claude_code"]`。
- `RoleRegistry.get_provider(provider, timeout, model)` 缓存键暂时保留；即使当前
  provider 单一，`timeout` 与 `model` 仍会影响实例行为。

## 后续可选

- [ ] 引入 `ruff`（lint + format）到 dev 依赖与 `pyproject.toml`。
- [ ] 引入类型检查（`mypy` 或 `pyright`）。
- [ ] 增加 CI 必跑 `pytest`，防止红测试再次合入。
- [ ] 为 LLM stage 增加更多离线/dry-run fixture，减少对真实 CLI 的隐式依赖。
