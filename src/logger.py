import os
import logging
from datetime import datetime
from src import config

def setup_logger():
    """
    Setup global logger configuration.
    Log directory: log/{CTP_NAME}/
    Log file: {CTP_NAME}_{Date}.log
    """
    ctp_name = config.CTP_NAME
    
    # Create log directory
    log_root = os.path.join(config.PROJECT_ROOT, "log")
    log_dir = os.path.join(log_root, ctp_name)
    
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
        
    # Log filename
    today_str = datetime.now().strftime("%Y-%m-%d")
    log_filename = f"{ctp_name}_{today_str}.log"
    log_filepath = os.path.join(log_dir, log_filename)
    
    # Configure logging
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Formatter
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(module)s - %(message)s')
    
    # File Handler
    file_handler = logging.FileHandler(log_filepath, encoding='utf-8')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Stream Handler (Console)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    
    logging.info(f"Logger initialized. Log file: {log_filepath}")

def log_info(msg: str):
    logging.info(msg)

def log_warning(msg: str):
    logging.warning(msg)

def log_error(msg: str):
    logging.error(msg)
