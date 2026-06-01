# PDF 阅读参考

## 作用

这是 PDF 阅读 skill 的辅助资料，用于说明常见抽取和阅读方法，不直接参与任务路由。

## 阅读优先级

1. 页码明确的问题，优先页级阅读
2. 章节明确的问题，优先章节阅读
3. 整份文档的问题，统一走文档级主链路

## 常见工具

- `pdfplumber`：文本与表格抽取
- `pypdf`：轻量文本与元数据读取
- `pypdfium2`：页面渲染
- `pytesseract`：OCR 兜底

## 示例

```python
from pypdf import PdfReader

reader = PdfReader("document.pdf")
text = reader.pages[0].extract_text()
```

```python
import pdfplumber

with pdfplumber.open("document.pdf") as pdf:
    page = pdf.pages[0]
    text = page.extract_text()
    tables = page.extract_tables()
```

## 注意

- 参考资料只帮助理解 PDF 处理方式，不替代 PDF MCP 的正式执行链。
- 图表页、扫描页和正文页要区别处理。
