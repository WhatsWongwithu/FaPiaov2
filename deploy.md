# 发票识别系统 部署文档（阿里云轻量服务器）

## 1. 购买服务器

1. 登录阿里云控制台：https://swas.console.aliyun.com
2. 购买轻量应用服务器：
   - 配置：2核2G
   - 系统：Ubuntu 22.04
   - 价格：约 ¥24/月起
3. 购买完成后，记录 **公网IP地址** 和设置的 **root密码**

## 2. SSH 登录服务器

在终端（Mac用Terminal，Windows用PowerShell）执行：

```bash
ssh root@你的服务器IP
```

输入密码登录。

## 3. 安装系统依赖

```bash
apt update && apt install -y python3 python3-pip nginx git
```

## 4. 克隆代码

```bash
cd /opt
git clone https://github.com/WhatsWongwithu/FaPiaov2.git fapiao
cd fapiao
```

## 5. 安装 Python 依赖

```bash
pip3 install -r requirements.txt
```

> 注意：RapidOCR 和 OpenCV 安装可能需要几分钟，请耐心等待。

## 6. 配置

```bash
cp config.ini.example config.ini
nano config.ini
```

修改 config.ini 内容（填入你的实际Key）：

```ini
[DEFAULT]
# DeepSeek API Key（兜底用，用户登录后用自己的Key覆盖）
DEEPSEEK_API_KEY=sk-你的deepseek_api_key

# 固定账号（2个，可修改用户名密码）
ACCOUNT1_USERNAME=user1
ACCOUNT1_PASSWORD=abc123
ACCOUNT2_USERNAME=user2
ACCOUNT2_PASSWORD=def456
```

保存退出（Ctrl+O → Enter → Ctrl+X）。

## 7. 初始化数据库

```bash
python3 -c "from app_v2 import init_db; init_db()"
```

看到以下输出说明成功：
```
  账号: user1 / abc123
  账号: user2 / def456
```

## 8. 启动服务（gunicorn）

先测试能否正常启动：

```bash
gunicorn -c gunicorn.conf.py app_v2:app
```

看到 `Listening at: http://0.0.0.0:8080` 说明成功。按 Ctrl+C 停止。

后台运行：

```bash
nohup gunicorn -c gunicorn.conf.py app_v2:app > /var/log/fapiao.log 2>&1 &
```

## 9. 配置 Nginx 反向代理

```bash
nano /etc/nginx/sites-available/fapiao
```

输入以下内容：

```nginx
server {
    listen 80;
    server_name _;

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 120s;
    }
}
```

保存退出。然后启用配置：

```bash
ln -sf /etc/nginx/sites-available/fapiao /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl restart nginx
```

## 10. 开放防火墙端口

在阿里云控制台：
1. 进入服务器详情页 → 防火墙
2. 添加规则：端口 80，协议 TCP，允许

## 11. 设置开机自启（可选但推荐）

```bash
nano /etc/systemd/system/fapiao.service
```

输入：

```ini
[Unit]
Description=FaPiao Invoice System
After=network.target

[Service]
WorkingDirectory=/opt/fapiao
ExecStart=/usr/bin/gunicorn -c gunicorn.conf.py app_v2:app
Restart=always
User=root

[Install]
WantedBy=multi-user.target
```

保存退出。然后：

```bash
# 先停掉之前的nohup进程
pkill -f gunicorn

# 用 systemd 管理
systemctl daemon-reload
systemctl enable fapiao
systemctl start fapiao
systemctl status fapiao
```

## 12. 访问

浏览器打开：

```
http://你的服务器IP
```

**首次使用流程**：
1. 输入用户名密码（默认 user1/abc123 或 user2/def456）
2. 首次登录自动跳转到设置页 → 输入自己的 DeepSeek API Key → 保存
3. 进入主页 → 上传发票
4. 第二次登录 → 自动记住 API Key → 直接使用

## 常见问题

### Q: 服务启动失败？
```bash
# 查看日志
cat /var/log/fapiao.log
# 或
journalctl -u fapiao -f
```

### Q: OCR 识别很慢？
2核2G服务器首次识别需要加载模型，第一次约30秒，之后会快一些。如果持续很慢，考虑升级到 2核4G。

### Q: 上传文件失败？
检查 Nginx 的 `client_max_body_size` 是否设置为 50M。

### Q: 如何更新代码？
```bash
cd /opt/fapiao
git pull
systemctl restart fapiao
```

### Q: 如何修改账号密码？
编辑 config.ini，修改用户名密码，然后：
```bash
cd /opt/fapiao
python3 -c "
from app_v2 import get_db, generate_password_hash
conn = get_db()
# 删除旧账号重新初始化
conn.execute('DELETE FROM users')
conn.commit()
conn.close()
from app_v2 import init_db
init_db()
"
systemctl restart fapiao
```
