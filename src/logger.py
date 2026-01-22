import os
import logging
from datetime import datetime
from src import config

def setup_logger():
    """
    设置全局日志配置。
    日志目录: log/{CTP_NAME}/
    日志文件: {CTP_NAME}_{Date}.log
    """
    ctp_name = config.CTP_NAME
    
    # 创建日志目录
    log_root = os.path.join(config.PROJECT_ROOT, "log")
    log_dir = os.path.join(log_root, ctp_name)
    
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
        
    # 日志文件名
    today_str = datetime.now().strftime("%Y-%m-%d")
    log_filename = f"{ctp_name}_{today_str}.log"
    log_filepath = os.path.join(log_dir, log_filename)
    
    # 配置日志
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # 格式化器
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(module)s - %(message)s')
    
    # 文件处理器
    file_handler = logging.FileHandler(log_filepath, encoding='utf-8')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # 流处理器 (控制台)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    
    logging.info(f"日志初始化完成。日志文件: {log_filepath}")

def log_info(msg: str):
    logging.info(msg)

def log_warning(msg: str):
    logging.warning(msg)

def log_error(msg: str):
    logging.error(msg)
