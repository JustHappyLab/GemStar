# discover_factors

## 目的
基于已有原始字段（OHLCV + 估值 + 财务指标）通过 DSL 表达式构造新因子，扩充因子池。

## 步骤
1. 阅读原始字段清单和现有 active 因子
2. 提出 3-6 个候选因子，每个包含表达式、经济假设、方向
3. 输出 JSON 数组（无 markdown 围栏）

## 输入
- raw fields: OHLCV、turnover_rate、pe_ttm、pb、total_mv、circ_mv
- existing factors: 当前 active 因子列表（避免重复）

## 输出
list[FactorProposal]，每个元素含 name/expression/hypothesis/direction/horizon
