"""Call the local Xiaomi OCR model and map its table-cell output to invoice rows."""

import base64
from io import BytesIO
import os
import re

import requests


OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get(
    "OLLAMA_MODEL", "longwayxu/xiaomi-ocr-0:bf16"
)
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "180"))

# Ask for the same cell-structured output that worked in the user's manual run.
INVOICE_PROMPT = """Extract the invoice table as a Markdown table with columns: 项目名称、规格型号、单位、数量、单价、金额、税率、税额. Keep each item on one row. Join wrapped lines within the same cell. Do not move values between columns."""

_CELL_RE = re.compile(r"<(?:fcel|lcel|ecel)>", re.IGNORECASE)
_TAG_RE = re.compile(r"</?(?:mdcel|fcel|lcel|ecel|nl)>", re.IGNORECASE)


def check_local_ocr_available():
    """Confirm that the configured Ollama model is installed and reachable."""
    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        response.raise_for_status()
        models = response.json().get("models", [])
    except requests.RequestException as exc:
        raise RuntimeError(
            "无法连接本地 Ollama。请先启动 Ollama 应用或服务后重试。"
        ) from exc
    except (ValueError, AttributeError) as exc:
        raise RuntimeError("Ollama 返回了无法识别的模型列表") from exc

    installed_names = {str(model.get("name", "")) for model in models}
    if OLLAMA_MODEL not in installed_names:
        raise RuntimeError(
            f"本地未找到模型 {OLLAMA_MODEL}。请先在 Ollama 中下载该模型。"
        )
    return True


def _image_bytes_for_path(file_path):
    """Return normalized PNG payloads; render PDFs at 200 DPI and cap edge size."""
    from PIL import Image

    def normalize(image):
        image = image.convert("RGB")
        max_edge = 2048
        if max(image.size) > max_edge:
            ratio = max_edge / max(image.size)
            image = image.resize(
                (round(image.width * ratio), round(image.height * ratio)),
                Image.Resampling.LANCZOS,
            )
        output = BytesIO()
        image.save(output, format="PNG", optimize=True)
        return output.getvalue()

    ext = os.path.splitext(file_path)[1].lower()
    if ext != ".pdf":
        with Image.open(file_path) as image:
            return [normalize(image)]

    import fitz

    pages = []
    with fitz.open(file_path) as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=200, alpha=False)
            with Image.open(BytesIO(pix.tobytes("png"))) as image:
                pages.append(normalize(image))
    return pages


def call_xiaomi_ocr(file_path):
    """Run Xiaomi OCR for each page and return the concatenated raw response."""
    page_images = _image_bytes_for_path(file_path)
    responses = []
    for index, image_bytes in enumerate(page_images, start=1):
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [{
                "role": "user",
                "content": INVOICE_PROMPT,
                "images": [base64.b64encode(image_bytes).decode("ascii")],
            }],
            "stream": False,
            "options": {"temperature": 0, "num_predict": 4096},
        }
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/chat", json=payload, timeout=OLLAMA_TIMEOUT
        )
        response.raise_for_status()
        content = response.json().get("message", {}).get("content", "").strip()
        if not content:
            raise ValueError(f"Xiaomi OCR 第 {index} 页没有返回识别内容")
        responses.append(content)
    return "\n<nl>\n".join(responses)


def parse_cell_table(raw_text):
    """Parse tagged-cell or Markdown table output into the existing item schema."""
    if not raw_text:
        raise ValueError("模型没有返回发票明细")

    # Some valid Markdown responses include cell-tag examples in notes/footer;
    # select the format from the table header, not from any incidental token.
    has_markdown_header = any(
        "|" in line and "项目名称" in line and "规格型号" in line
        for line in raw_text.splitlines()
    )
    if has_markdown_header:
        return _parse_markdown_table(raw_text)
    if "<fcel>" not in raw_text.lower():
        return _parse_markdown_table(raw_text)

    # Ignore any filename/title/prose before the first marked table header.
    start = raw_text.lower().find("<mdcel>")
    if start >= 0:
        raw_text = raw_text[start:]

    rows = re.split(r"<nl>", raw_text, flags=re.IGNORECASE)
    parsed = []
    expected_header = ["项目名称", "规格型号", "单位", "数量", "单价", "金额", "税率/征收率", "税额"]

    for raw_row in rows:
        raw_row = raw_row.strip()
        if not raw_row:
            continue
        # A visual line break without <nl> may occur inside a row. Cell tags
        # are authoritative, so remove whitespace around cell boundaries.
        raw_cells = _CELL_RE.split(raw_row)
        cells = []
        for cell in raw_cells:
            cell = _TAG_RE.sub("", cell)
            cell = re.sub(r"[\r\n\t]+", "", cell)
            cell = re.sub(r" {2,}", " ", cell).strip()
            cells.append(cell)
        while cells and not cells[0]:
            cells.pop(0)
        if not cells:
            continue

        normalized = [c.replace(" ", "") for c in cells]
        if sum(1 for h in expected_header if any(h in c for c in normalized)) >= 5:
            continue
        row_labels = [re.sub(r"\s+", "", c) for c in cells[:2]]
        if any("合计" in c or "价税合计" in c for c in row_labels):
            continue

        # Rows may contain extra empty marker cells; invoice details use the
        # first eight columns in the documented order.
        cells = (cells + [""] * 8)[:8]
        name, spec, _unit, qty, price, amount, tax_rate, tax = cells
        if not name and not spec:
            continue
        if not any(re.search(r"\d", value or "") for value in (qty, price, amount, tax)):
            continue
        parsed.append({
            "name": name.replace("*", "").strip(),
            "spec": spec,
            "qty": qty,
            "price": price,
            "amount": amount,
            "tax_rate": tax_rate,
            "tax": tax,
        })

    if not parsed:
        raise ValueError("识别结果中未解析到有效的发票明细行")
    return parsed


def parse_table_totals(raw_text):
    """Extract the table's subtotal amount/tax when the model included them."""
    if not raw_text:
        return {}

    cleaned = re.sub(r"</?md>", "", raw_text, flags=re.IGNORECASE)
    markdown_lines = [line.strip() for line in cleaned.splitlines()
                      if line.strip().startswith("|") and line.strip().endswith("|")]
    if any("项目名称" in line and "规格型号" in line for line in markdown_lines):
        header_map = {}
        start_rows = 0
        for index, line in enumerate(markdown_lines):
            cells = [cell.strip() for cell in line[1:-1].split("|")]
            normalized = [re.sub(r"\s+", "", cell) for cell in cells]
            if not any("项目名称" in cell for cell in normalized):
                continue
            for field, label in (("amount", "金额"), ("tax", "税额")):
                for col, cell in enumerate(normalized):
                    if label in cell:
                        header_map[field] = col
                        break
            start_rows = index + 1
            break
        for line in markdown_lines[start_rows:]:
            cells = [cell.strip() for cell in line[1:-1].split("|")]
            labels = [re.sub(r"\s+", "", cell) for cell in cells[:2]]
            if any("合计" in label for label in labels):
                return {
                    key: cells[col].replace("￥", "").replace("¥", "").strip()
                    for key, col in header_map.items() if col < len(cells)
                }
        return {}

    for row in re.split(r"<nl>", raw_text, flags=re.IGNORECASE):
        if "<fcel>" not in row.lower() and "<lcel>" not in row.lower():
            continue
        cells = [re.sub(r"[\r\n\t]+", "", cell).strip()
                 for cell in _CELL_RE.split(row)]
        cells = [_TAG_RE.sub("", cell).strip() for cell in cells]
        while cells and not cells[0]:
            cells.pop(0)
        if cells and "合计" in re.sub(r"\s+", "", cells[0]):
            cells += [""] * max(0, 8 - len(cells))
            return {
                "amount": cells[5].replace("￥", "").replace("¥", "").strip(),
                "tax": cells[7].replace("￥", "").replace("¥", "").strip(),
            }
    return {}


def _parse_markdown_table(raw_text):
    """Read a Markdown pipe table; map header names instead of relying on order."""
    aliases = {
        "name": ("项目名称", "品名", "货物或应税劳务、服务名称"),
        "spec": ("规格型号", "规格"),
        "unit": ("单位",),
        "qty": ("数量",),
        "price": ("单价",),
        "amount": ("金额",),
        "tax_rate": ("税率", "税率/征收率", "征收率"),
        "tax": ("税额",),
    }
    cleaned = re.sub(r"</?md>", "", raw_text, flags=re.IGNORECASE)
    lines = [line.strip() for line in cleaned.splitlines()
             if line.strip().startswith("|") and line.strip().endswith("|")]

    def split_row(line):
        return [re.sub(r"\\([|])", r"\1", cell).strip()
                for cell in line[1:-1].split("|")]

    header_map = {}
    header_line = -1
    for line_index, line in enumerate(lines):
        cells = split_row(line)
        normalized = [re.sub(r"\s+", "", cell) for cell in cells]
        candidate_map = {}
        for field, labels in aliases.items():
            for index, cell in enumerate(normalized):
                if any(label.replace(" ", "") in cell for label in labels):
                    candidate_map[field] = index
                    break
        if len(candidate_map) >= 6 and "name" in candidate_map and "amount" in candidate_map:
            header_map = candidate_map
            header_line = line_index
            break
    if not header_map:
        raise ValueError("模型结果中未找到包含必需列名的 Markdown 表头")

    parsed = []
    for line in lines[header_line + 1:]:
        cells = split_row(line)
        if not cells or all(re.fullmatch(r"[:\-\s]*", cell or "") for cell in cells):
            continue
        row_labels = [re.sub(r"\s+", "", cell) for cell in cells[:2]]
        if any("合计" in cell or "价税合计" in cell for cell in row_labels):
            continue
        values = {
            field: cells[index] if index < len(cells) else ""
            for field, index in header_map.items()
        }
        if "name" not in values and "spec" not in values:
            continue
        if not any(re.search(r"\d", values.get(key, ""))
                   for key in ("qty", "price", "amount", "tax")):
            continue
        parsed.append({
            "name": values.get("name", "").replace("*", "").strip(),
            "spec": values.get("spec", ""),
            "qty": values.get("qty", ""),
            "price": values.get("price", ""),
            "amount": values.get("amount", ""),
            "tax_rate": values.get("tax_rate", ""),
            "tax": values.get("tax", ""),
        })
    if not parsed:
        raise ValueError("模型结果中未找到可解析的 Markdown 发票明细表")
    return parsed
