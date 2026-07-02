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
2. 数量：纯数字。如果数量未识别到，留空""，绝对不要默认为1或任何猜测值。系统后处理会用 金额÷单价 自动计算
3. 单价：保留原始精度
4. 金额：该行的小计金额
5. 税率：如"13%"
6. 税额：该行的税额
7. 合计金额：表格底部"合计"行的金额（不是价税合计）
8. 合计税额：表格底部"合计"行的税额
9. 发票总金额：价税合计（小写）金额
10. 如果某个字段无法识别，留空字符串""

关键规则——数量与单价的处理：
OCR常把"数量"和"单价"合并成一个数字（因为两列靠得很近）。例如数量"2"和单价"30"被OCR读成"230"。
处理方式：
1. 如果数量和单价分别识别到了，分别填入qty和price字段
2. 如果你认为某个数字是"数量+单价"的合并值（数字异常大），将合并值放入price字段，qty字段留空""
3. 如果只识别到单价、没有数量，qty留空""
4. 绝对不要将qty默认为1或任何猜测值，不确定就留空""，系统后处理会用"金额=数量×单价"自动拆分和验证
5. 不要自行做数学计算或拆分数字

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


# ==================== 数量×单价=金额 验证修复 ====================

def _parse_number(s):
    """将字符串解析为浮点数，处理空格、逗号、￥等"""
    if not s:
        return None
    s = str(s).strip().replace(",", "").replace(" ", "").replace("￥", "").replace("¥", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _try_split_merged(merged_str, amount, tolerance=0.005):
    """
    尝试将合并的"数量+单价"字符串拆分为 (数量, 单价)
    使得 数量 × 单价 ≈ 金额
    例: "2261.0619469026549", amount=522.12 → ("2", "261.0619469026549")
    """
    s = str(merged_str).strip().replace(",", "").replace(" ", "").replace("￥", "").replace("¥", "")
    if not s:
        return None
    amount_f = _parse_number(amount)
    if amount_f is None or amount_f <= 0:
        return None

    # qty 通常是 1-2 位整数，从左到右尝试每个拆分点
    for i in range(1, min(len(s), 10)):
        left = s[:i]
        right = s[i:]
        try:
            qty = float(left)
            price = float(right)
        except ValueError:
            continue
        if qty <= 0 or price <= 0:
            continue
        # 数量通常是整数或≤2位小数，拒绝把长小数当数量(如823.0088不是数量)
        if _count_decimals(left) > 2:
            continue
        product = qty * price
        if abs(product - amount_f) <= max(amount_f * tolerance, 0.5):
            qty_str = str(int(qty)) if qty == int(qty) else left
            return (qty_str, right)
    return None


def _count_decimals(s):
    """计算字符串中小数点后的位数"""
    s = str(s).strip().replace(",", "").replace(" ", "").replace("￥", "").replace("¥", "")
    if "." not in s:
        return 0
    parts = s.split(".")
    if len(parts) == 2:
        return len(parts[1])
    return 0


def _validate_and_fix_items(items):
    """
    验证并修复每行明细的 数量×单价=金额 关系
    处理OCR问题:
    1. 数量被合并到单价中 (如 "2"+"30" → "230")
    2. 数量完全丢失 (单价正确，qty为空)
    3. LLM错误拆分合并值 (如把"1769.91"拆成qty=176, price=9.91)
    4. qty和price被交换 (qty有多位小数, price是整数)
    """
    for item in items:
        qty_raw = item.get("qty", "")
        price_raw = item.get("price", "")
        amount_raw = item.get("amount", "")

        amount_f = _parse_number(amount_raw)
        if amount_f is None or amount_f <= 0:
            continue

        qty_f = _parse_number(qty_raw)
        price_f = _parse_number(price_raw)

        # 预检查: 数量必须是正整数(允许±0.02 OCR误差)
        # 非整数数量(如0.07, 1.05)说明价格错误，清空数量让后续策略重新计算
        if qty_f is not None:
            if qty_f < 0.5 or abs(qty_f - round(qty_f)) > 0.02:
                item["qty"] = ""
                qty_raw = ""
                qty_f = None

        # 策略0: 检查qty和price是否被交换
        # qty通常是整数或短小数，price通常是长小数(>2位)
        if qty_f is not None and price_f is not None:
            qty_dec = _count_decimals(qty_raw)
            price_dec = _count_decimals(price_raw)
            if qty_dec > 2 and price_dec <= 2 and qty_f > price_f:
                # qty像price，price像qty → 交换
                item["qty"] = price_raw.strip()
                item["price"] = qty_raw.strip()
                qty_raw, price_raw = price_raw, qty_raw
                qty_f, price_f = price_f, qty_f

        # 检查当前是否已正确 (0.5%容差)
        if qty_f is not None and price_f is not None:
            product = qty_f * price_f
            if abs(product - amount_f) <= max(amount_f * 0.005, 0.5):
                continue  # 验证通过，无需修复

        fixed = False

        # 策略1: 拆分price (qty被合并到price中，或qty缺失但price是合并值)
        if price_raw:
            result = _try_split_merged(price_raw, amount_f)
            if result:
                item["qty"] = result[0]
                item["price"] = result[1]
                fixed = True

        # 策略1.5: LLM可能错误拆分了合并值，尝试用合并值作为price重新计算qty
        if not fixed and qty_raw and price_raw:
            combined_str = str(qty_raw).strip().replace(",", "").replace(" ", "") + \
                           str(price_raw).strip().replace(",", "").replace(" ", "")
            combined_f = _parse_number(combined_str)
            if combined_f and combined_f > 0:
                calc_qty = amount_f / combined_f
                if abs(calc_qty - round(calc_qty)) < 0.02 and round(calc_qty) > 0:
                    item["qty"] = str(int(round(calc_qty)))
                    item["price"] = combined_str
                    fixed = True

        # 策略2: 拆分qty (price被合并到qty中)
        if not fixed and qty_raw:
            result = _try_split_merged(qty_raw, amount_f)
            if result:
                item["qty"] = result[0]
                item["price"] = result[1]
                fixed = True

        # 策略3: qty有效且为正整数但price缺失/错误 → price = amount / qty
        if not fixed and qty_f is not None and qty_f > 0:
            calc_price = amount_f / qty_f
            item["price"] = str(round(calc_price, 6))
            fixed = True

        # 策略4: price有效但qty缺失/错误 → qty = amount / price
        # 仅当计算出的qty为正整数时才填入，否则留空(不猜)
        if not fixed and price_f is not None and price_f > 0:
            calc_qty = amount_f / price_f
            if abs(calc_qty - round(calc_qty)) < 0.02 and round(calc_qty) > 0:
                item["qty"] = str(int(round(calc_qty)))
                fixed = True
            # else: 计算出的qty非整数，说明price可能错误，留空不填

    return items


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

    # 验证并修复 数量×单价=金额
    _validate_and_fix_items(items)

    return {
        "date": result.get("date", ""),
        "invoice_num": result.get("invoice_num", ""),
        "total_amount": result.get("total_amount", ""),
        "seller_name": result.get("seller_name", ""),
        "total_amount_sum": result.get("total_amount_sum", ""),
        "total_tax_sum": result.get("total_tax_sum", ""),
        "items": items,
    }
