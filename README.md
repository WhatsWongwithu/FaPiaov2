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
         → 选择 Python OCR 流程或本地票据识别
         → 结构化JSON → Excel
```

## 安装

```bash
# 1. 安装Python依赖
pip install -i https://mirrors.aliyun.com/pypi/simple/ flask openpyxl requests PyMuPDF rapidocr-onnxruntime opencv-python-headless

# 2. （可选）配置 Flask 会话密钥
# 部署环境请设置稳定的随机密钥；不要提交密钥到 Git。
export FLASK_SECRET_KEY="替换为你生成的随机长字符串"

# 3. 使用 Python OCR 流程时配置 API 密钥
cp config.ini.example config.ini
# 编辑 config.ini 填入你的 DeepSeek API Key
# 申请地址: https://platform.deepseek.com

# 4. 启动
python app_v2.py
```

### 本地票据识别（Ollama）

模型权重由 Ollama 单独下载和管理，不包含在本 GitHub 项目中。使用本地识别的电脑或服务器需要先安装并启动 Ollama，然后下载项目默认使用的模型：

```bash
ollama pull longwayxu/xiaomi-ocr-0:bf16
```

确认 `ollama list` 能看到该模型后，在程序设置中启用“本地票据识别”。默认连接地址为 `http://127.0.0.1:11434`。如果 Ollama 在另一台机器上，可设置 `OLLAMA_BASE_URL`；需要切换模型时设置 `OLLAMA_MODEL`。模型文件较大，应在每台部署机器上单独下载。

部署到云服务器时，服务器需要有可运行 Ollama 的硬件和足够的内存/磁盘，并在服务器上下载模型；仅部署 Web 项目代码不会自动提供模型推理服务。

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
