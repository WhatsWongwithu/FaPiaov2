"""
发票识别系统 V3 - OCR + DeepSeek LLM解析
上海辉驰包装设备有限公司 财务部

OCR识别文字 → DeepSeek理解表格结构 → 提取全部字段
启动后浏览器访问 http://localhost:8080
"""

import os
import uuid
from flask import Flask, request, jsonify, send_file, render_template
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from datetime import datetime

from ocr_engine import OCREngine
from llm_parser import parse_with_deepseek
from config import get_deepseek_key

DEEPSEEK_API_KEY = get_deepseek_key()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff")
PDF_EXTENSIONS = (".pdf",)
ALL_EXTENSIONS = IMAGE_EXTENSIONS + PDF_EXTENSIONS

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

# 全局OCR引擎（加载一次，复用）
ocr_engine = OCREngine()


# ==================== Excel生成 ====================
def write_excel(invoices, output_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "进项发票记录"

    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )
    header_font = Font(name="微软雅黑", bold=True, size=10)
    title_font = Font(name="微软雅黑", bold=True, size=14)
    data_font = Font(name="微软雅黑", size=10)
    header_fill = PatternFill(
        start_color="D9E1F2", end_color="D9E1F2", fill_type="solid"
    )
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left_align = Alignment(horizontal="left", vertical="center", wrap_text=True)

    # 新表头：序号、开票日期、品名、规格、数量、单价、金额、税率、税额、发票总金额、票号、供应商名称
    num_cols = 12
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=num_cols)
    ws["A1"] = "进项发票记录"
    ws["A1"].font = title_font
    ws["A1"].alignment = center

    headers = [
        "序号", "开票日期", "品名", "规格", "数量", "单价",
        "金额", "税率", "税额", "发票总金额", "票号", "供应商名称",
    ]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=2, column=col, value=h)
        cell.font = header_font
        cell.alignment = center
        cell.border = thin_border
        cell.fill = header_fill

    row = 3
    serial = 1
    for inv in invoices:
        first_row = True
        for item in inv["items"]:
            if first_row:
                ws.cell(row=row, column=1, value=serial)
                ws.cell(row=row, column=2, value=inv["date"])
                ws.cell(row=row, column=10, value=inv["total_amount"])
                ws.cell(row=row, column=11, value=f"NO.{inv['invoice_num']}")
                ws.cell(row=row, column=12, value=inv["seller_name"])
                first_row = False
            else:
                ws.cell(row=row, column=12, value=inv["seller_name"])

            ws.cell(row=row, column=3, value=item["name"])
            ws.cell(row=row, column=4, value=item["spec"])
            ws.cell(row=row, column=5, value=item["qty"])
            ws.cell(row=row, column=6, value=item["price"])
            ws.cell(row=row, column=7, value=item["amount"])
            ws.cell(row=row, column=8, value=item["tax_rate"])
            ws.cell(row=row, column=9, value=item["tax"])
            row += 1
        serial += 1

    max_row = row - 1
    for r in range(3, max_row + 1):
        for c in range(1, num_cols + 1):
            cell = ws.cell(row=r, column=c)
            cell.border = thin_border
            cell.alignment = left_align if c in (3, 4, 12) else center
            cell.font = data_font

    col_widths = [6, 12, 16, 18, 8, 14, 12, 8, 12, 14, 26, 26]
    for i, w in enumerate(col_widths, 1):
        ws.column_dimensions[chr(64 + i)].width = w

    # 合计行
    sum_row = max_row + 1
    ws.cell(row=sum_row, column=3, value="合计")
    ws.cell(row=sum_row, column=3).font = header_font
    ws.cell(row=sum_row, column=3).alignment = center
    # 金额合计
    ws.cell(row=sum_row, column=7, value=f"=SUM(G3:G{max_row})")
    ws.cell(row=sum_row, column=7).font = header_font
    ws.cell(row=sum_row, column=7).alignment = center
    # 税额合计
    ws.cell(row=sum_row, column=9, value=f"=SUM(I3:I{max_row})")
    ws.cell(row=sum_row, column=9).font = header_font
    ws.cell(row=sum_row, column=9).alignment = center
    # 发票总金额合计
    ws.cell(row=sum_row, column=10, value=f"=SUM(J3:J{max_row})")
    ws.cell(row=sum_row, column=10).font = header_font
    ws.cell(row=sum_row, column=10).alignment = center
    for c in range(1, num_cols + 1):
        ws.cell(row=sum_row, column=c).border = thin_border

    wb.save(output_path)


# ==================== 路由 ====================
invoices_store = []


@app.route("/")
def index():
    return render_template("index_v2.html")


@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "未收到文件"}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALL_EXTENSIONS:
        return jsonify({"error": f"不支持的格式: {ext}"}), 400

    safe_name = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(UPLOAD_DIR, safe_name)
    file.save(file_path)

    try:
        ocr_results = ocr_engine.recognize(file_path)
        invoice = parse_with_deepseek(ocr_results, DEEPSEEK_API_KEY)
        invoice["id"] = uuid.uuid4().hex
        invoice["filename"] = file.filename
        invoices_store.append(invoice)

        return jsonify(
            {
                "success": True,
                "invoice": {
                    "id": invoice["id"],
                    "filename": invoice["filename"],
                    "date": invoice["date"],
                    "invoice_num": invoice["invoice_num"],
                    "total_amount": invoice["total_amount"],
                    "seller_name": invoice["seller_name"],
                    "item_count": len(invoice["items"]),
                    "items": invoice["items"],
                },
            }
        )
    except Exception as e:
        return jsonify({"error": f"处理异常: {str(e)}"}), 200
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


@app.route("/results")
def results():
    return jsonify(
        {
            "invoices": [
                {
                    "id": inv["id"],
                    "filename": inv["filename"],
                    "date": inv["date"],
                    "invoice_num": inv["invoice_num"],
                    "total_amount": inv["total_amount"],
                    "seller_name": inv["seller_name"],
                    "item_count": len(inv["items"]),
                    "items": inv["items"],
                }
                for inv in invoices_store
            ]
        }
    )


@app.route("/download")
def download():
    if not invoices_store:
        return jsonify({"error": "没有数据"}), 400

    filename = f"进项发票记录_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    output_path = os.path.join(UPLOAD_DIR, filename)
    write_excel(invoices_store, output_path)

    return send_file(output_path, as_attachment=True, download_name=filename)


@app.route("/clear")
def clear():
    invoices_store.clear()
    return jsonify({"success": True})


@app.route("/delete/<invoice_id>")
def delete_invoice(invoice_id):
    global invoices_store
    invoices_store = [inv for inv in invoices_store if inv["id"] != invoice_id]
    return jsonify({"success": True})


if __name__ == "__main__":
    print("=" * 55)
    print("  发票识别系统 V3 - OCR + DeepSeek LLM")
    print("  上海辉驰包装设备有限公司 财务部")
    print("=" * 55)
    print("\n  OCR识别 → DeepSeek理解表格 → 提取全部字段")
    print("  浏览器访问: http://localhost:8080\n")
    app.run(host="0.0.0.0", port=8080, debug=True)
