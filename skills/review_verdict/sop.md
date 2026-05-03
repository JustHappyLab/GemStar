# review_verdict

## 目的
解读 RuleJudge 判定结果，输出人类可读的 ReviewNotesV1。

## 步骤
1. 解析 verdict 中各硬门通过/失败状态
2. 结合 metrics 评估策略质量
3. 检查 segments 中的分段表现一致性
4. 识别风险点并给出 confidence

## 输入
- verdict: VerdictV1
- metrics: MetricsV1
- segments: list[SegmentMetricV1]
- factor_health: FactorHealthReportV1 (optional)

## 输出
ReviewNotesV1 JSON
