"""
LLM解析器 - 使用DeepSeek API解析OCR识别的文字
将OCR文字按空间布局排版后，交给LLM理解表格结构并提取全部字段
"""

import json
import requests

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

# 提示词：告诉DeepSeek如何解析发票
SYSTEM_PROMPT = """你是一个专业的发票信息提取助手。用户会给你发票OCR识别的文字内容，每段文字前标注了X坐标（横向位置），按行排列。
X坐标可以帮助你判断文字属于表格的哪一列：X越小越靠左（品名列），X越大越靠右（税额列）。

请提取发票中的所有信息，以JSON格式返回。

提取规则：
1. 品名：去掉星号标记，保留分类和名称。如"*齿轮*减速机"提取为"齿轮减速机"
2. 数量：纯数字。OCR可能漏识别数量列，此时用 金额÷单价 计算数量
3. 单价：保留原始精度
4. 金额：该行的小计金额
5. 税率：如"13%"
6. 税额：该行的税额
7. 合计金额：表格底部"合计"行的金额（不是价税合计）
8. 合计税额：表格底部"合计"行的税额
9. 发票总金额：价税合计（小写）金额
10. 如果某个字段无法识别，留空字符串""

关键规则——数量与单价的拆分：
OCR常把"数量"和"单价"合并成一个数字。例如数量"1"和单价"119.469"被OCR读成"1119.469"。
请用数学验证来拆分：
- 验证公式：金额 ≈ 单价 × 数量，税额 ≈ 金额 × 税率
- 如果某个数字×1≠金额，但去掉首位数字后×该数字=金额，则首位数字是数量
  例：OCR读到"1119.469"，金额=119.47 → 数量=1，单价=119.469
- 如果OCR没有识别到数量列，直接用 金额÷单价 计算数量（取整数或保留2位小数）

关键规则——规格型号换行合并：
规格可能分两行显示，如"5IK90GU-YF-"和"J+5GU10KB"是同一个规格，需合并为"5IK90GU-YF-J+5GU10KB"。

关键规则——不要把合计行当明细行：
"合计"行只有金额合计和税额合计，没有品名和规格，不要算作明细行。

返回JSON格式如下（只返回JSON，不要其他文字）：
{
  "invoice_num": "发票号码",
  "date": "YYYY/MM/DD",
  "seller_name": "销售方名称",
  "total_amount": "价税合计",
  "total_amount_sum": "合计金额",
  "total_tax_sum": "合计税额",
  "items": [
    {
      "name": "品名（含分类）",
      "spec": "规格型号",
      "qty": "数量",
      "price": "单价",
      "amount": "金额",
      "tax_rate": "税率",
      "tax": "税额"
    }
  ]
}"""


def format_ocr_text(ocr_results):
    """
    将OCR结果按空间布局排版成文本
    按Y坐标分行，每行内按X坐标排序
    同时标注每段文字的大致列位置（左/中左/中/中右/右）
    """
    if not ocr_results:
        return ""

    # 计算页面宽度，用于判断列位置
    all_x = [r[1] for r in ocr_results]
    page_width = max(all_x) if all_x else 1000

    # 按Y坐标聚类成行（Y差距<25的视为同一行）
    sorted_results = sorted(ocr_results, key=lambda r: r[2])
    rows = []
    current_row = []
    current_y = None

    for text, cx, cy in sorted_results:
        if current_y is None or abs(cy - current_y) < 25:
            current_row.append((cx, text))
            current_y = cy if current_y is None else current_y
        else:
            rows.append(current_row)
            current_row = [(cx, text)]
            current_y = cy
    if current_row:
        rows.append(current_row)

    # 每行内按X排序，用 | 分隔
    lines = []
    for row in rows:
        row.sort(key=lambda x: x[0])
        line = " | ".join(text for _, text in row)
        lines.append(line)

    return "\n".join(lines)


def format_ocr_text_with_coords(ocr_results):
    """
    将OCR结果排版成带坐标信息的文本
    格式: [x坐标] 文字内容 （按行排列）
    坐标帮助LLM判断文字属于表格的哪一列
    """
    if not ocr_results:
        return ""

    # 按Y坐标聚类成行
    sorted_results = sorted(ocr_results, key=lambda r: r[2])
    rows = []
    current_row = []
    current_y = None

    for text, cx, cy in sorted_results:
        if current_y is None or abs(cy - current_y) < 25:
            current_row.append((cx, text, cy))
            current_y = cy if current_y is None else current_y
        else:
            rows.append(current_row)
            current_row = [(cx, text, cy)]
            current_y = cy
    if current_row:
        rows.append(current_row)

    # 每行内按X排序，标注X坐标
    lines = []
    for row in rows:
        row.sort(key=lambda x: x[0])
        parts = []
        for cx, text, _ in row:
            parts.append(f"[x={cx:.0f}] {text}")
        lines.append(" | ".join(parts))

    return "\n".join(lines)


def parse_with_deepseek(ocr_results, api_key):
    """
    用DeepSeek API解析OCR结果
    返回与invoice_parser.py相同的结构
    """
    ocr_text = format_ocr_text_with_coords(ocr_results)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"请解析以下发票OCR文字：\n\n{ocr_text}"},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
    }

    resp = requests.post(
        DEEPSEEK_API_URL, headers=headers, json=payload, timeout=60
    )
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    result = json.loads(content)

    # 确保字段完整
    items = result.get("items", [])
    for item in items:
        for key in ["name", "spec", "qty", "price", "amount", "tax_rate", "tax"]:
            if key not in item:
                item[key] = ""

    return {
        "date": result.get("date", ""),
        "invoice_num": result.get("invoice_num", ""),
        "total_amount": result.get("total_amount", ""),
        "seller_name": result.get("seller_name", ""),
        "total_amount_sum": result.get("total_amount_sum", ""),
        "total_tax_sum": result.get("total_tax_sum", ""),
        "items": items,
    }
