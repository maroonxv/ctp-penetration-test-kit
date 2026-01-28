import os
import yaml
from typing import Dict, Any

def load_env(env_path: str) -> Dict[str, str]:
    env_vars = {}
    if not os.path.exists(env_path):
        return env_vars
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                key, value = line.split('=', 1)
                env_vars[key.strip()] = value.strip()
    return env_vars

def load_yaml_config(config_path: str) -> Dict[str, Any]:
    if not os.path.exists(config_path):
        return {}
    with open(config_path, 'r', encoding='utf-8') as f:
        try:
            return yaml.safe_load(f) or {}
        except yaml.YAMLError:
            return {}

# 路径配置
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")
CONFIG_YAML_PATH = os.path.join(PROJECT_ROOT, "config.yaml")

# 加载配置
ENV_VARS = load_env(ENV_PATH)
YAML_CONFIG = load_yaml_config(CONFIG_YAML_PATH)

def save_env(env_path: str, data: Dict[str, str]) -> None:
    """更新或保存 .env 文件"""
    lines = []
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

    new_lines = []
    processed_keys = set()
    
    # 更新现有键值
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            new_lines.append(line)
            continue
        
        if '=' in line:
            key, _ = stripped.split('=', 1)
            key = key.strip()
            if key in data:
                new_lines.append(f"{key}={data[key]}\n")
                processed_keys.add(key)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)
            
    # 添加新键值
    for key, value in data.items():
        if key not in processed_keys:
            # 如果最后一行不是换行符，先添加一个换行
            if new_lines and not new_lines[-1].endswith('\n'):
                new_lines.append('\n')
            new_lines.append(f"{key}={value}\n")
            
    with open(env_path, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)


# 全局常量
CTP_NAME = ENV_VARS.get("CTP_NAME", "Unknown")
CTP_USERNAME = ENV_VARS.get("CTP_USERNAME", "")
CTP_BROKER_ID = ENV_VARS.get("CTP_BROKER_ID", "")
CTP_TD_SERVER = ENV_VARS.get("CTP_TD_SERVER", "")
CTP_APP_ID = ENV_VARS.get("APPID", "")
CTP_AUTH_CODE = ENV_VARS.get("CTP_AUTH_CODE", "")
ATOMIC_WAIT_SECONDS = 7
RPC_PORT = 9999
RPC_HOST = "127.0.0.1"

# CTP 配置
CTP_SETTING = {
    "用户名": CTP_USERNAME,
    "密码": ENV_VARS.get("CTP_PASSWORD", ""),
    "经纪商代码": CTP_BROKER_ID,
    "交易服务器": CTP_TD_SERVER,
    "行情服务器": ENV_VARS.get("CTP_MD_SERVER", ""),
    "产品名称": CTP_APP_ID,
    "授权编码": CTP_AUTH_CODE,
    "产品信息": ENV_VARS.get("CTP_PRODUCT_INFO", "")
}

# 从 YAML 读取测试配置
TEST_SYMBOL = YAML_CONFIG.get("test_symbol", "IF2602")
SAFE_BUY_PRICE = float(YAML_CONFIG.get("safe_buy_price", 4700.0))
DEAL_BUY_PRICE = float(YAML_CONFIG.get("deal_buy_price", 4800.0))

# 市场状态错误测试配置
REST_TEST_SYMBOL = YAML_CONFIG.get("rest_test_symbol", "LC2607")
REST_TEST_PRICE = float(YAML_CONFIG.get("rest_test_price", 168220))

# 从 YAML 读取风控阈值
RISK_THRESHOLDS = YAML_CONFIG.get("risk_thresholds", {
    "max_order_count": 5,
    "max_cancel_count": 5,
    "max_symbol_order_count": 2
})
