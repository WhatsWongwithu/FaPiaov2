# 发票识别系统

上海辉驰包装设备有限公司 · 财务部

## 功能

- 拍照/上传发票 → 自动识别全部内容 → 归类到Excel
- 支持 **PDF电子发票**（直接提取文字，100%准确）和 **图片发票**（OCR识别）
- 提取字段：品名、规格、数量、单价、金额、税率、税额、合计、价税合计

## 技术架构

```
发票文件 → PyMuPDF(直接提取) / RapidOCR(放大2x识别)
         → 按行列排版 + X坐标标注
         → DeepSeek LLM 理解表格结构
         → 结构化JSON → Excel
```

## 安装

```bash
# 1. 安装Python依赖
pip install -i https://mirrors.aliyun.com/pypi/simple/ flask openpyxl requests PyMuPDF rapidocr-onnxruntime opencv-python-headless

# 2. 配置API密钥
cp config.ini.example config.ini
# 编辑 config.ini 填入你的 DeepSeek API Key
# 申请地址: https://platform.deepseek.com

# 3. 启动
python app_v2.py
```

打开浏览器访问 http://localhost:8080

## 使用

1. 将发票照片/PDF放入界面（拖拽上传）
2. 系统自动识别，实时显示进度
3. 查看识别结果表格
4. 点击"下载Excel"导出

## 文件说明

| 文件 | 说明 |
|---|---|
| `app_v2.py` | Web服务主程序 |
| `ocr_engine.py` | OCR引擎（PDF直提 + 图片OCR） |
| `llm_parser.py` | DeepSeek LLM解析模块 |
| `invoice_parser.py` | 坐标匹配解析器（备用） |
| `config.py` | 配置读取 |
| `config.ini` | API密钥（需自行创建，不提交到Git） |
| `templates/index_v2.html` | Web界面 |
