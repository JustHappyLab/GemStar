# generate_tickets

## 目的
基于市场状态、事件和因子健康状况，生成研究工单，输出 ResearchTicketV1 列表。

## 步骤
1. 分析当前 market regime 和 style bias
2. 结合近期事件识别因子调整机会
3. 检查因子池健康状态，找出薄弱因子
4. 生成 1-3 个可测试的研究假设

## 输入
- regime: MarketRegimeV1
- events: list[SignalEventV1]
- factor_health: FactorHealthReportV1
- factor_pool: FactorPoolV1

## 输出
list[ResearchTicketV1] JSON array
