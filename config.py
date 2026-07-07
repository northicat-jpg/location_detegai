"""项目配置参数 - 从 config.json 加载，文件不存在时使用默认值"""

import json
import os
import sys


def _get_config_path():
    """获取 config.json 的路径，优先查找 exe 同目录（方便用户修改）"""
    # PyInstaller 打包后，sys.executable 指向 exe 所在目录
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        config_path = os.path.join(exe_dir, 'config.json')
        if os.path.exists(config_path):
            return config_path

    # 开发模式下，从脚本所在目录查找
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, 'config.json')
    if os.path.exists(config_path):
        return config_path

    # 都找不到，返回 None，使用默认值
    return None


def _load_config():
    """加载配置，返回字典"""
    path = _get_config_path()
    if path is None:
        print("[配置] 未找到 config.json，使用默认配置")
        return {}

    try:
        with open(path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        print(f"[配置] 已加载: {path}")
        return cfg
    except Exception as e:
        print(f"[配置] 读取失败 ({e})，使用默认配置")
        return {}


_cfg = _load_config()

# === TCP 服务器 ===
TCP_HOST = _cfg.get("tcp_host", "0.0.0.0")
TCP_PORT = _cfg.get("tcp_port", 8080)
TCP_BACKLOG = _cfg.get("tcp_backlog", 64)

# === 传感器参数 ===
SENSOR_BAUD = _cfg.get("sensor_baud", 9600)
READ_TIMEOUT = _cfg.get("read_timeout", 2.0)
MEASURE_INTERVAL = _cfg.get("measure_interval", 0.5)
DISTANCE_THRESHOLD_MM = _cfg.get("distance_threshold_mm", 2500)

# === 客户端到库位编码映射 ===
CLIENT_LOCATION_MAP = _cfg.get("client_location_map", {})

# === 数据库 ===
MYSQL_URL = _cfg.get("mysql_url", "127.0.0.1")
MYSQL_PORT = _cfg.get("mysql_port", 3306)
MYSQL_USERNAME = _cfg.get("mysql_username", "root")
MYSQL_PASSWORD = _cfg.get("mysql_password", "")
MYSQL_NAME = _cfg.get("mysql_name", "rcs")
DB_POOL_SIZE = _cfg.get("db_pool_size", 10)