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


def common_count_from_start(arr1, arr2):
    count = 0
    for i in range(min(len(arr1), len(arr2))):
        if arr1[i] == arr2[i]:
            count += 1
        else:
            break
    return count


def levenshtein_distance(s1, s2):
    m, n = len(s1), len(s2)

    # 创建一个 (m+1) x (n+1) 的二维数组
    dp = [[0] * (n + 1) for _ in range(m + 1)]

    # 初始化第一行和第一列
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j

    # 计算编辑距离
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if s1[i - 1] == s2[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])

    return dp[m][n]


def find_most_common_parent_super(a: str, b: list[str], include_nam_set: set[str]):
    """通过 h name 比对，找到最可能的 func, 优先选用 h name, 和 c name 中相同的方法, 用多个选项是， 从路径中判断， 编辑距离允许误差为 3"""
    ret_rank_set = [set() for _ in range(1 + 3)]

    for c_path in b:
        c_name = c_path.split("/")[-1].split(".")[0]
        for include_name in include_nam_set:
            if (distance_score := levenshtein_distance(c_name, include_name)) <= 2:
                ret_rank_set[distance_score].add(c_path)

    for collect in ret_rank_set:
        if len(collect) == 1:
            return collect
        if len(collect) > 1:
            return find_most_common_parent(a, collect)

    return find_most_common_parent(a, b)


def find_most_common_parent(a: str, b: list[str]):
    """
    找出 b 中和 a 有相同父目录最多的一个路径

    Args:
    a: 一个路径
    b: 一组路径

    Returns:
    b 中和 a 有相同父目录最多的一个路径
    """

    pa = pathlib.Path(a)
    path_counts = collections.defaultdict(list)
    mx = -1
    for pathB in b:
        pb = pathlib.Path(pathB).parent
        count = common_count_from_start(pa.parts, pb.parts)
        if count >= mx:
            mx = count
            path_counts[count].append(pathB)

    # 对于有多个结果的， 选择目录最短的返回
    if len(path_counts[mx]) == 1:
        return path_counts[mx]
    mi = 99
    path_length = collections.defaultdict(list)
    for pathB in path_counts[mx]:
        length = len(pathlib.Path(pathB).parts)
        if length <= mi:
            path_length[length].append(pathB)
            mi = length
    # 最终返回最长相同路径中最短路径的
    return path_length[mi]


def test():
    test_c_path = "/mnt/wd01/github/linux_old1/kernel/kallsyms_selftest.c"
    test_h_path = "/mnt/wd01/github/linux_old1/include/crypto/authenc.h"
    # test_c_path = "/mnt/wd01/github/linux_old1/tools/testing/radix-tree/maple.c"
    test_c_path = "/mnt/wd01/github/linux_old1/arch/alpha/kernel/core_wildfire.c"
    ret = extract_c_file(test_c_path)
    logging.info(ret)
