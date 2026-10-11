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

## 安装与启动（macOS）

项目代码不会包含 Ollama 模型权重。第一次设置时，脚本会安装 Python 依赖，并通过 Ollama 下载默认模型（约 1.8 GB，实际大小以 Ollama 显示为准）。项目和 Ollama 应安装在同一台电脑上。

```bash
# 1. 安装 Git、Python 3.11 或更高版本，以及 Ollama
# Ollama 下载页：https://ollama.com/download/mac
# 如果已安装 Homebrew，安装 Ollama 也可用：brew install --cask ollama

# 2. 下载项目
git clone https://github.com/WhatsWongwithu/FaPiaov2.git
cd FaPiaov2

# 3. 安装 Python 依赖、启动 Ollama 并下载本地模型
chmod +x setup_macos.sh start_macos.sh
./setup_macos.sh

# 4. 启动发票程序
./start_macos.sh
```

浏览器访问 http://127.0.0.1:8080。新账号默认使用“本地票据识别”；如果账号之前保存过 DeepSeek API Key，则进入“设置”切换并保存。以后每次使用，在项目目录运行 `./start_macos.sh` 即可。

### 安装脚本做什么

- `setup_macos.sh`：创建项目虚拟环境、安装 `requirements.txt` 中的 Python 包；检查 Ollama，必要时询问是否通过 Homebrew 安装；启动 Ollama API 并下载模型。
- `start_macos.sh`：启动 Ollama（如果尚未运行）、检查模型和 Python 环境，然后启动发票程序。

模型由 Ollama 单独下载和管理，不会被提交到 GitHub。默认 Ollama API 地址为 `http://127.0.0.1:11434`。需要更换模型时，运行安装脚本前设置 `OLLAMA_MODEL`，以后启动程序时也要在同一 shell 环境中设置该变量。连接非本机 Ollama 服务时可设置 `OLLAMA_BASE_URL`；macOS 启动脚本用于本机 Ollama。

本地开发环境若未设置 `FLASK_SECRET_KEY`，程序每次启动会生成临时密钥，服务器重启后需要重新登录。部署环境请设置稳定且私密的密钥，例如 `export FLASK_SECRET_KEY="$(openssl rand -hex 32)"`，并妥善保存。

### 其他系统 / Python OCR 云端流程

macOS 脚本不适用于 Linux 或 Windows。其他系统请自行安装 Python 3.11+、Ollama 和 Git，克隆项目后执行 `pip install -r requirements.txt`、`ollama pull longwayxu/xiaomi-ocr-0:bf16`，再运行 `python app_v2.py`。确保 Ollama API 正在运行，并在设置中启用本地票据识别。

如需使用 OCR 识别与云端结构化解析，请在项目目录创建 `config.ini` 并填入 DeepSeek API Key（可参考 `config.ini.example`），然后在设置中选择该识别方式。`config.ini` 不要提交到 GitHub。

部署到云服务器时，服务器上的程序会连接服务器自己的 Ollama；它不会自动连接访问网页的用户电脑。服务器需要有可运行模型的硬件、足够的内存和磁盘，并在服务器上单独下载模型。生产部署还应设置稳定且私密的 `FLASK_SECRET_KEY` 环境变量。

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
