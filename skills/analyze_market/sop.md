# analyze_market

## 目的
从日线和指数数据中评估当前市场状态，输出 MarketRegimeV1。

## 步骤
1. 计算近20日市场收益、波动率、涨跌比、量能变化
2. 提取创业板指20日收益和波动率
3. 将统计数据格式化为中文摘要
4. 调用 LLM 评估市场 regime

## 输入
- daily_df: 日线行情数据
- index_df: 创业板指数据
- reference_date: 评估日期

## 输出
MarketRegimeV1 JSON
