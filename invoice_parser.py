"""
发票解析器 - 将识别的文字解析为结构化发票数据
支持增值税专用发票 / 电子发票（全电发票）
"""

import re
from collections import defaultdict


def parse_invoice(ocr_results):
    """
    解析OCR/PDF结果为结构化发票数据

    返回: {
        "date": "2026/04/25",
        "invoice_num": "26372000001906300531",
        "total_amount": "34150.00",
        "seller_name": "诸城市惠林精密机械有限公司",
        "total_amount_sum": "30221.22",   # 合计金额
        "total_tax_sum": "3928.78",       # 合计税额
        "items": [{"name": "齿轮减速机", "spec": "5GU30KB", "qty": "1",
                    "price": "1119.47", "amount": "1119.47",
                    "tax_rate": "13%", "tax": "145.53"}, ...]
    }
    """
    texts = [r[0] for r in ocr_results]

    # ========== 1. 提取头部字段 ==========
    invoice_num = _extract_invoice_num(ocr_results, texts)
    date = _extract_date(ocr_results, texts)
    seller_name = _extract_seller_name(ocr_results)
    total_amount = _extract_total_amount(ocr_results, texts)
    total_amount_sum, total_tax_sum = _extract_totals(ocr_results)

    # ========== 2. 提取明细行 ==========
    items = _extract_line_items(ocr_results)

    return {
        "date": date,
        "invoice_num": invoice_num,
        "total_amount": total_amount,
        "seller_name": seller_name,
        "total_amount_sum": total_amount_sum,
        "total_tax_sum": total_tax_sum,
        "items": items,
    }


# ==================== 头部字段提取 ====================
def _extract_invoice_num(ocr_results, texts):
    """提取发票号码（兼容PDF标签和值分开的情况）"""
    for text in texts:
        m = re.search(r"发票号码[：:]\s*(\d+)", text)
        if m:
            return m.group(1)
    for text, cx, cy in ocr_results:
        if re.match(r"^发票号码[：:]?\s*$", text.strip()):
            best_dist = float("inf")
            best_val = ""
            for t2, x2, y2 in ocr_results:
                if x2 > cx and abs(y2 - cy) < 20:
                    m = re.match(r"^(\d{15,25})$", t2.strip())
                    if m and (x2 - cx) < best_dist:
                        best_dist = x2 - cx
                        best_val = m.group(1)
            if best_val:
                return best_val
    return ""


def _extract_date(ocr_results, texts):
    """提取开票日期（兼容PDF标签和值分开的情况）"""
    for text in texts:
        m = re.search(r"开票日期[：:]\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
        if m:
            y, mo, d = m.groups()
            return f"{y}/{int(mo):02d}/{int(d):02d}"
        m = re.search(r"开票日期[：:]\s*(\d{4}[/\-]\d{1,2}[/\-]\d{1,2})", text)
        if m:
            return m.group(1).replace("-", "/")
    for text, cx, cy in ocr_results:
        if re.match(r"^开票日期[：:]?\s*$", text.strip()):
            for t2, x2, y2 in ocr_results:
                if x2 > cx and abs(y2 - cy) < 20:
                    m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", t2)
                    if m:
                        y, mo, d = m.groups()
                        return f"{y}/{int(mo):02d}/{int(d):02d}"
    return ""


def _extract_seller_name(ocr_results):
    """提取销方名称"""
    seller_x = None
    for text, cx, cy in ocr_results:
        if "销售方" in text:
            seller_x = cx
            break

    # 找所有"名称："标签
    name_labels = []
    for text, cx, cy in ocr_results:
        if re.match(r"^名称[：:]?\s*$", text.strip()):
            name_labels.append((cx, cy))

    # 对每个标签，找右侧最近的文字
    name_values = []
    for label_x, label_y in name_labels:
        nearest_text = None
        nearest_dist = float("inf")
        for text, cx, cy in ocr_results:
            if re.match(r"^名称[：:]?\s*$", text.strip()):
                continue
            if re.match(r"^(统一|发票|开票|销售|购买|项目|规格|单位|数量|单价|金额|税率|税额|价税|合计|备注|收款|复核|开户|银行)", text.strip()):
                continue
            if cx >= label_x - 20 and abs(cy - label_y) < 30:
                dist = cx - label_x + abs(cy - label_y)
                if 0 <= dist < nearest_dist:
                    nearest_dist = dist
                    nearest_text = text.strip()
        if nearest_text:
            is_seller = seller_x is not None and label_x > seller_x - 50
            name_values.append((label_x, is_seller, nearest_text))

    for _, is_seller, name in name_values:
        if is_seller:
            return name
    if name_values:
        name_values.sort(key=lambda x: -x[0])
        return name_values[0][2]

    # 回退：正则匹配
    for text, cx, cy in ocr_results:
        m = re.search(r"名称[：:]\s*(.+)", text)
        if m:
            name_values.append((cx, m.group(1).strip()))
    if name_values:
        name_values.sort(key=lambda x: -x[0])
        return name_values[0][1]
    return ""


def _extract_total_amount(ocr_results, texts):
    """提取价税合计（小写），兼容PDF标签和值分开"""
    # 方法1: 正则直接匹配
    for text in texts:
        m = re.search(r"[（(]小写[)）][￥¥]?\s*([\d,.]+)", text)
        if m:
            return m.group(1).replace(",", "")
        m = re.search(r"[（(]小写[)）].*?[￥¥]([\d,.]+)", text)
        if m:
            return m.group(1).replace(",", "")

    # 方法2: 找"（小写）"标签，在其右侧找带￥的数字
    for text, cx, cy in ocr_results:
        if "小写" in text:
            best_dist = float("inf")
            best_val = ""
            for t2, x2, y2 in ocr_results:
                if x2 > cx and abs(y2 - cy) < 20:
                    # 匹配 ￥550.00 或 550.00
                    m = re.match(r"^[￥¥]?\s*([\d,.]+)$", t2.strip())
                    if m and (x2 - cx) < best_dist:
                        best_dist = x2 - cx
                        best_val = m.group(1).replace(",", "")
            if best_val:
                return best_val

    # 方法3: 找最后一个带￥的数字
    amounts = []
    for text in texts:
        m = re.search(r"[￥¥]([\d,.]+)", text)
        if m:
            amounts.append(m.group(1).replace(",", ""))
    if amounts:
        return amounts[-1]
    return ""


def _extract_totals(ocr_results):
    """
    提取合计行：合计金额 和 合计税额
    合计行通常有"合计"标签，后面跟着两个带￥的数字
    """
    total_amount = ""
    total_tax = ""

    # 找"合计"行的Y坐标
    heji_y = None
    for text, cx, cy in ocr_results:
        text_nospace = text.replace(" ", "").replace("\u3000", "")
        if text_nospace in ("合计",) or "合计" in text_nospace:
            if "价税合计" not in text_nospace:
                heji_y = cy
                break
        # PDF中"合"和"计"可能分开
        if text_nospace in ("合", "计") and heji_y is None:
            heji_y = cy

    if heji_y is None:
        return "", ""

    # 在合计行附近找带￥的数字（通常有2个：金额合计和税额合计）
    yens = []
    for text, cx, cy in ocr_results:
        if abs(cy - heji_y) < 15:
            # ¥486.73 或单独的486.73
            m = re.search(r"[￥¥]?\s*([\d,.]+)", text)
            if m and re.search(r"\d", text):
                val = m.group(1).replace(",", "").replace("￥", "").replace("¥", "")
                yens.append((cx, val))
            elif text.strip() in ("¥", "￥"):
                yens.append((cx, ""))

    # 合并相邻的￥和数字
    merged = []
    for cx, val in yens:
        if merged and not merged[-1][1] and val:
            merged[-1] = (merged[-1][0], val)
        elif val:
            merged.append((cx, val))

    if len(merged) >= 2:
        merged.sort()
        total_amount = merged[0][1]
        total_tax = merged[1][1]
    elif len(merged) == 1:
        total_amount = merged[0][1]

    return total_amount, total_tax


# ==================== 明细行提取 ====================
def _extract_line_items(ocr_results):
    """从表格区域提取明细行"""
    header_keywords = {
        "name": ["项目名称", "货物或应税劳务", "服务名称"],
        "spec": ["规格型号", "规格"],
        "unit": ["单位"],
        "qty": ["数量"],
        "price": ["单价"],
        "amount": ["金额"],
        "tax_rate": ["税率", "征收率"],
        "tax": ["税额"],
    }

    col_boundaries = {}
    header_y = None

    header_keywords_flat = []
    for kws in header_keywords.values():
        header_keywords_flat.extend(kws)

    for text, cx, cy in ocr_results:
        text_nospace = text.replace(" ", "").replace("\u3000", "")
        for col, keywords in header_keywords.items():
            for kw in keywords:
                if kw in text_nospace and col not in col_boundaries:
                    col_boundaries[col] = cx
                    if header_y is None or cy < header_y:
                        header_y = cy

    if not header_y:
        return []

    # --- 列X边界 ---
    col_centers = sorted(col_boundaries.items(), key=lambda x: x[1])
    col_names = [c[0] for c in col_centers]
    col_xs = [c[1] for c in col_centers]

    def get_column(x):
        for i in range(len(col_xs)):
            if i < len(col_xs) - 1:
                mid = (col_xs[i] + col_xs[i + 1]) / 2
                if x < mid:
                    return col_names[i]
            else:
                if x > col_xs[i] - 100:
                    return col_names[i]
        return None

    # --- 收集表格区域文字 ---
    table_end_y = _find_table_end(ocr_results, header_y)

    col_data = {k: [] for k in header_keywords}

    for text, cx, cy in ocr_results:
        if cy < header_y or cy >= table_end_y:
            continue
        text_nospace = text.replace(" ", "").replace("\u3000", "")
        is_header = any(kw in text_nospace for kw in header_keywords_flat)
        if is_header:
            continue
        col = get_column(cx)
        if col and col in col_data:
            col_data[col].append((cy, text))

    for col in col_data:
        col_data[col].sort()

    # 合并换行的品名和规格
    for col_name in ["name", "spec"]:
        entries = col_data.get(col_name, [])
        if len(entries) <= 1:
            continue
        merged = []
        for y, text in entries:
            if merged:
                prev_y, prev_text = merged[-1]
                if abs(y - prev_y) < 30:
                    merged[-1] = (prev_y, prev_text + text)
                    continue
            merged.append((y, text))
        col_data[col_name] = merged

    # --- 内容纠偏：根据内容特征修正列归属 ---
    # 单价通常是长小数（>4位小数），数量通常是短整数
    # 如果qty列里有长小数，移到price列；如果price列里有短整数，移到qty列
    _fix_qty_price_columns(col_data)

    # --- 组装明细行 ---
    anchor_col = None
    for candidate in ["amount", "tax", "tax_rate"]:
        if col_data.get(candidate):
            valid = []
            for y, text in col_data[candidate]:
                if candidate == "tax_rate":
                    if re.search(r"\d+%", text):
                        valid.append((y, text))
                else:
                    if re.search(r"\d", text):
                        valid.append((y, text))
            if valid:
                anchor_col = candidate
                col_data[anchor_col] = valid
                break

    if not anchor_col:
        anchor_col = "spec" if col_data.get("spec") else "name"
        if not col_data.get(anchor_col):
            return []

    base_items = col_data[anchor_col]

    # 动态校准Y偏移
    all_cols = ["name", "spec", "qty", "price", "amount", "tax_rate", "tax"]
    col_offsets = {}
    for col_name in all_cols:
        col_entries = col_data.get(col_name, [])
        if not col_entries or not base_items:
            col_offsets[col_name] = 0
            continue
        best_offset = 0
        best_match_count = 0
        for offset in range(-80, 81, 5):
            match_count = 0
            used_idx = set()
            for anchor_y, _ in base_items:
                search_y = anchor_y + offset
                best_dist = float("inf")
                best_j = None
                for j, (y, _) in enumerate(col_entries):
                    if j in used_idx:
                        continue
                    d = abs(y - search_y)
                    if d < best_dist and d < 40:
                        best_dist = d
                        best_j = j
                if best_j is not None:
                    used_idx.add(best_j)
                    match_count += 1
            if match_count > best_match_count:
                best_match_count = match_count
                best_offset = offset
        col_offsets[col_name] = best_offset

    # 贪心匹配
    used = defaultdict(set)
    items = []

    for i, (base_y, _) in enumerate(base_items):
        item = {k: "" for k in ["name", "spec", "qty", "price", "amount", "tax_rate", "tax"]}

        for col_name in all_cols:
            col_entries = col_data.get(col_name, [])
            if not col_entries:
                continue
            search_y = base_y + col_offsets.get(col_name, 0)
            best_idx = None
            best_dist = float("inf")
            for j, (y, text) in enumerate(col_entries):
                if j in used[col_name]:
                    continue
                dist = abs(y - search_y)
                if dist < best_dist and dist < 50:
                    best_dist = dist
                    best_idx = j
            if best_idx is not None:
                used[col_name].add(best_idx)
                text = col_entries[best_idx][1]
                if col_name == "name":
                    item["name"] = _clean_name(text)
                elif col_name == "spec":
                    item["spec"] = _clean_spec(text)
                elif col_name == "tax_rate":
                    item["tax_rate"] = _clean_tax_rate(text)
                else:
                    item[col_name] = _clean_number(text)

        if item["name"] or item["spec"]:
            items.append(item)

    return items


def _fix_qty_price_columns(col_data):
    """
    根据内容特征修正数量和单价列的归属
    - 单价通常是长小数（含小数点且小数位>2）
    - 数量通常是短数字（整数或小数位<=2）
    """
    qty_entries = col_data.get("qty", [])
    price_entries = col_data.get("price", [])

    if not qty_entries:
        return

    # 检查qty列中是否有应该属于price的长小数
    to_move_to_price = []
    remaining_qty = []
    for y, text in qty_entries:
        text_clean = text.strip().replace(" ", "").replace(",", "")
        # 长小数（小数点后超过2位）很可能是单价
        if re.match(r"^\d+\.\d{3,}$", text_clean):
            to_move_to_price.append((y, text))
        else:
            remaining_qty.append((y, text))

    if to_move_to_price:
        col_data["qty"] = remaining_qty
        col_data["price"] = price_entries + to_move_to_price
        col_data["price"].sort()


def _find_table_end(ocr_results, header_y):
    """找到表格结束Y坐标"""
    end_keywords = ["合计", "价税合计", "大写", "小写", "￥"]
    end_y = header_y + 2000

    for text, cx, cy in ocr_results:
        if cy > header_y:
            text_nospace = text.replace(" ", "").replace("\u3000", "")
            for kw in end_keywords:
                if kw in text_nospace or kw in text:
                    if cy < end_y:
                        end_y = cy
                    break
            if text_nospace in ("合", "计") and cy < end_y:
                end_y = cy

    return end_y


# ==================== 清理函数 ====================
def _clean_name(text):
    """清理品名：*齿轮*减速机 → 齿轮减速机（保留分类，去掉星号）"""
    text = text.strip()
    text = text.replace("*", "")
    return text


def _clean_spec(text):
    """清理规格型号"""
    return text.strip()


def _clean_number(text):
    """清理数字"""
    text = text.strip().replace(" ", "").replace(",", "").replace("￥", "").replace("¥", "")
    m = re.search(r"[\d.]+", text)
    return m.group(0) if m else text


def _clean_tax_rate(text):
    """清理税率：保留百分号"""
    text = text.strip().replace(" ", "")
    m = re.search(r"\d+%", text)
    return m.group(0) if m else text
