# Excel 读取参考

## 作用

这是结构化数据分析 skill 的辅助资料，不参与路由，不直接决定任务类型，只用于在需要时提醒如何稳定读取 Excel。

## 基本原则

1. 优先使用 `pandas.read_excel()`。
2. 先看列名和前几行，再决定分析操作。
3. 不要把预览结果误当成完整数据集。

## 常用模式

```python
import pandas as pd

df = pd.read_excel("data.xlsx")
preview = pd.read_excel("data.xlsx", nrows=10)
selected = pd.read_excel("data.xlsx", usecols=["列1", "列2"])
```

## 多工作表

```python
import pandas as pd

excel_file = pd.ExcelFile("workbook.xlsx")
for sheet_name in excel_file.sheet_names:
    df = pd.read_excel(excel_file, sheet_name=sheet_name)
```

## 注意

- 大文件先做 schema 预览。
- 优先保留原始列名，再做列名归一化。
- 如果已有专用工具，就不要临时退回 `python_repl`。
