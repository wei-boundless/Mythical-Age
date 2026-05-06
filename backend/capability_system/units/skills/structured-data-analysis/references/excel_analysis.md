# Excel 分析参考

## 作用

这是结构化数据分析 skill 的辅助资料，用于说明常见数据分析原语，不直接参与运行时路由。

## 常见操作

- 条件过滤
- 分组汇总
- 排序
- Top N
- 极值记录
- 派生指标

## 示例

```python
filtered = df[df["sales"] > 10000]
summary = df.groupby("region")["sales"].sum()
top5 = df.sort_values("sales", ascending=False).head(5)
```

## 透视与合并

```python
pivot = pd.pivot_table(
    df,
    values="sales",
    index="region",
    columns="product",
    aggfunc="sum",
    fill_value=0,
)

merged = pd.merge(sales, customers, on="customer_id", how="left")
```

## 注意

- 先明确任务类型，再选分析原语。
- 对结构化数据问题，优先走 structured_data MCP，不要把参考文档当执行路径。
