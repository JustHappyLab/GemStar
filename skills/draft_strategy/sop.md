# draft_strategy

## 目的
根据研究工单草拟策略 YAML 配置，输出可直接回测的 StrategyConfigV1。

## 步骤
1. 解析研究工单中的假设和建议
2. 从因子池中选择合适的因子组合
3. 分配权重（非负，和为1.0）
4. 设置 top_n、rebalance、backtest 参数
5. 输出合法 YAML

## 输入
- tickets: list[ResearchTicketV1]
- factor_pool: FactorPoolV1

## 输出
StrategyConfigV1 YAML
