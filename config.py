"""
配置读取模块
从config.ini读取API密钥，避免硬编码在源码中
"""

import os
from configparser import ConfigParser

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini")

_config = None


def _load_config():
    global _config
    if _config is None:
        _config = ConfigParser()
        if os.path.exists(CONFIG_PATH):
            _config.read(CONFIG_PATH, encoding="utf-8")
    return _config


def get_baidu_keys():
    """获取百度OCR API Key和Secret Key"""
    cfg = _load_config()
    if cfg.has_section("baidu") or cfg.has_option("DEFAULT", "BAIDU_API_KEY"):
        api_key = cfg.get("DEFAULT", "BAIDU_API_KEY", fallback="") or cfg.get("baidu", "api_key", fallback="")
        secret_key = cfg.get("DEFAULT", "BAIDU_SECRET_KEY", fallback="") or cfg.get("baidu", "secret_key", fallback="")
        return api_key, secret_key
    return "", ""


def get_deepseek_key():
    """获取DeepSeek API Key"""
    cfg = _load_config()
    return cfg.get("DEFAULT", "DEEPSEEK_API_KEY", fallback="") or cfg.get("deepseek", "api_key", fallback="")
