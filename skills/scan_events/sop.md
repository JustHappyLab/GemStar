# scan_events

## 目的
从量化信号中识别显著市场事件，输出 SignalEventV1 列表。

## 步骤
1. 扫描行情数据中的异常模式（放量、跳空、连板等）
2. 结合板块数据判断轮动信号
3. 检查北向资金异动
4. 汇总为事件列表

## 输入
- daily_df: 日线行情数据
- reference_date: 扫描日期

## 输出
list[SignalEventV1] JSON array
