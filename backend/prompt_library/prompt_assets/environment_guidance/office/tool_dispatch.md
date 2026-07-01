---
title: Office 工具派发工作提示
---

工具调用必须服务于资料处理的下一步。优先使用文件搜索、文件读取、来源检索和办公产物工具；不要用命令行替代可见的文件/检索能力。
办公文档创建、编辑、转换和验证必须派发给统一办公文档处理能力，并传入明确的 action、path、output_path 和结构化 operations；不要让 agent 自己拼接二进制文件或用普通 workspace_edit 写 Office/PDF 内容。
调用 `office_document` 时按任务选择参数：`inspect/read` 只需要源路径和读取范围；`create` 使用目标路径、target_file_type 和创建 operations；`edit` 使用源路径、output_path 和结构化 operations；`allow_overwrite` 只有在用户明确要求覆盖时才可设为 true。
Word 编辑使用 paragraph_index、paragraph_number 或 contains；Excel 编辑使用 sheet_name 和 cell_ref；PowerPoint 编辑使用 slide_number/slide_index、shape_id/shape_index 或 contains；PDF 第一阶段优先使用 pages 做页面级操作。锚点不明确时先 inspect/read 或询问，不要模糊替换。
当前成熟操作范围：Word append_paragraph/append_section/replace_paragraph_text/insert_paragraph_after；Excel create_sheet/update_cell/set_formula/append_rows；PowerPoint add_slide/insert_text_box/replace_shape_text；PDF add_page/append_text/delete_pages/reorder_pages/split_pages/merge_pdfs。PDF 正文文本编辑、Excel 公式重算和高保真渲染验证不足时要说明限制。
参数必须来自用户指定范围或当前读取事实；路径、引用和输出文件名要明确。
多个互不依赖的只读检索可以并行；同一文件写入、格式转换或产物生成应串行并保留证据。
