import pathlib
import re
import collections
import logging.config
from src.protos import text_mate_pb2_grpc
from src.protos import text_mate_pb2
import grpc
from c_formatter_42.run import run_all
import json

# 加载配置文件
logging.config.fileConfig("config/logging.conf")
MAX_MESSAGE_LENGTH = 20 * 1024 * 1024


# 默认情况下不会包含隐藏文件
def count_files_and_size(directory):
    total_files = 0
    total_size = 0

    for p in pathlib.Path(directory).rglob("*"):
        if p.is_file():
            # 增加文件数量
            total_files += 1
            # 增加文件大小
            total_size += p.stat().st_size

    return total_files, total_size


def find_c_files(directory):
    path = pathlib.Path(directory)
    for i, file in enumerate(path.glob("**/*.c")):
        yield file
        # if i>1000:
        #     break


def find_h_files(directory):
    path = pathlib.Path(directory)
    for i, file in enumerate(path.glob("**/*.h")):
        yield file
        # if i>1000:
        #     break


def count_file():
    c_file_count = 0
    h_file_count = 0
    for _ in find_c_files(project_source_path):
        c_file_count += 1
    for _ in find_h_files(project_source_path):
        h_file_count += 1
    logging.info("c file count: %s", c_file_count)
    logging.info("h file count: %s", h_file_count)


def code_str_count(code_list):
    count = 0
    for text in code_list:
        cleaned_text = re.sub(r"\s+", "", text)
        # 统计字符数量
        count += len(cleaned_text)
    return count


thread_count = 20
GRPC_URI = "127.0.0.1"
GRPC_PORT = [port for port in range(40050, 40050 + thread_count)]

# Create a gRPC channel for each server
channels = [
    grpc.insecure_channel(
        f"{GRPC_URI}:{prot}",
        options=[
            ("grpc.max_send_message_length", MAX_MESSAGE_LENGTH),
            ("grpc.max_receive_message_length", MAX_MESSAGE_LENGTH),
        ],
    )
    for prot in GRPC_PORT
]

# Create a stub for each channel
stubs = [text_mate_pb2_grpc.TextMateServiceStub(channel) for channel in channels]


def extract_c_file(file_path, god_path, index):
    stub = stubs[index % len(stubs)]
    scope = "source.c"
    # with grpc.insecure_channel(f"{GRPC_URI}:{prot}", options=[
    #     ('grpc.max_send_message_length', MAX_MESSAGE_LENGTH),
    #     ('grpc.max_receive_message_length', MAX_MESSAGE_LENGTH),
    # ],) as channel:
    #     stub = text_mate_pb2_grpc.TextMateServiceStub(channel)

    file_path = pathlib.Path(file_path)
    # 读取文件内容
    with open(file_path, "rt", errors="ignore") as file:
        data = file.read()
    try:
        data = run_all(data)
    except RuntimeError as e:
        error_message = str(e)
        if "not support Objective-C" not in error_message:
            logging.warning("clang-format fail:%s,%s", file_path, e)
    except Exception as e:
        logging.warning("clang-format fail:%s,%s", file_path, e)
        logging.exception(e)
    response = stub.GetTextMatePlain(text_mate_pb2.CodeSource(text=data, scope=scope))
    # logging.info(response.text)
    result = json.loads(response.text)

    # 转换 local include 到 path
    local_include_file_path = []
    for path in result.get("local_include", []):
        path = file_path.parent.joinpath(path).resolve().absolute()
        local_include_file_path.append(path.as_posix().replace(god_path, ""))
    result["local_include"] = local_include_file_path

    file_name_str = file_path.as_posix()
    result["c_name"] = file_name_str.replace(god_path, "").split("/")[-1]

    result["file_path"] = file_path.as_posix().replace(god_path, "")

    path_out_include = file_name_str.split("include")[-1].strip("/").split("/")[-4:]
    path_name_list = []
    for i in range(len(path_out_include)):
        path_name_list.append("/".join(path_out_include[i:]))
    result["my_include_name_list"] = path_name_list

    return result


def test():
    test_c_path = "/mnt/wd01/github/linux_old1/kernel/kallsyms_selftest.c"
    test_h_path = "/mnt/wd01/github/linux_old1/include/crypto/authenc.h"
    # test_c_path = "/mnt/wd01/github/linux_old1/tools/testing/radix-tree/maple.c"
    test_c_path = "/mnt/wd01/github/linux_old1/arch/alpha/kernel/core_wildfire.c"
    ret = extract_c_file(test_c_path)
    logging.info(ret)
