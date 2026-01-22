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

# 路径配置
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")

# 加载环境变量
ENV_VARS = load_env(ENV_PATH)

# 全局常量
CTP_NAME = ENV_VARS.get("CTP_NAME", "Unknown")
ATOMIC_WAIT_SECONDS = 7
RPC_PORT = 9999
RPC_HOST = "127.0.0.1"

# CTP 配置
CTP_SETTING = {
    "用户名": ENV_VARS.get("CTP_USERNAME", ""),
    "密码": ENV_VARS.get("CTP_PASSWORD", ""),
    "经纪商代码": ENV_VARS.get("CTP_BROKER_ID", ""),
    "交易服务器": ENV_VARS.get("CTP_TD_SERVER", ""),
    "行情服务器": ENV_VARS.get("CTP_MD_SERVER", ""),
    "产品名称": ENV_VARS.get("APPID", ""),
    "授权编码": ENV_VARS.get("CTP_AUTH_CODE", "")
}

# 测试配置
TEST_SYMBOL = "IF2602"  # 测试目标合约
SAFE_BUY_PRICE = 4000.0
DEAL_BUY_PRICE = 4660.0
