# draft_strategy

## 目的
根据研究工单草拟策略 YAML 配置，输出可直接回测的 StrategyConfigV1。

## 步骤
1. 解析研究工单中的假设和建议
2. 从因子池中选择合适的因子组合
3. 分配权重（非负，和为1.0）
4. 固定 `timer.mode: full`，只做选股策略草拟
5. 设置 top_n、rebalance、backtest 参数
6. 输出合法 YAML

## 择时边界
- 本 skill 不自由生成择时模型。
- 不输出 LSTM/GRU 参数、序列长度、预测周期、训练轮数、阈值或再训练周期。
- 自动策略草拟阶段只允许 `timer.mode: full`。
- 受控择时模板由 `docs/timing-policy.md` 管理，必须先实现、回测、评审，再进入 live 或 leaderboard 比较。

## 输入
- tickets: list[ResearchTicketV1]
- factor_pool: FactorPoolV1

## 输出
StrategyConfigV1 YAML
