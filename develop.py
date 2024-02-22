import unittest
from src.linux_kernel_v2.utils import (extract_c_file, count_files_and_size)
import logging.config
import json
import os

# 加载配置文件
logging.config.fileConfig('config/logging.conf')


god_path = os.getcwd() + "/tests/data/2024/"

# file_path = f"tests/data/2024/core_wildfire.c"
file_path = f"tests/data/2024/kallsyms_selftest.c"
# file_path = f"tests/data/2024/maple.c"
file_path = "/mnt/wd01/github/linux_old1/arch/alpha/kernel/audit.c"

ret = extract_c_file(file_path, god_path)
with open("out/dev.json",'wt')as f:
    json.dump(ret,f, indent=4)
# logging.info( json.dumps(ret, indent=4))

logging.info(count_files_and_size(god_path))