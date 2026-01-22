import os
from typing import Dict

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

# Paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")

# Load Env
ENV_VARS = load_env(ENV_PATH)

# Global Constants
CTP_NAME = ENV_VARS.get("CTP_NAME", "Unknown")
ATOMIC_WAIT_SECONDS = 7
RPC_PORT = 9999
RPC_HOST = "127.0.0.1"

# CTP Setting
CTP_SETTING = {
    "用户名": ENV_VARS.get("CTP_USERNAME", ""),
    "密码": ENV_VARS.get("CTP_PASSWORD", ""),
    "经纪商代码": ENV_VARS.get("CTP_BROKER_ID", ""),
    "交易服务器": ENV_VARS.get("CTP_TD_SERVER", ""),
    "行情服务器": ENV_VARS.get("CTP_MD_SERVER", ""),
    "产品名称": ENV_VARS.get("CTP_PRODUCT_NAME", ENV_VARS.get("APP_ID", "")),
    "授权编码": ENV_VARS.get("CTP_AUTH_CODE", ""),
    "AppID": ENV_VARS.get("APP_ID", "")
}

# Test Config
TEST_SYMBOL = "IF2601"  # Target contract for testing
SAFE_BUY_PRICE = 4000.0
DEAL_BUY_PRICE = 4660.0
