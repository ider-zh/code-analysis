import pathlib
import re
import collections
import logging.config

# 加载配置文件
logging.config.fileConfig('config/logging.conf')

# 默认情况下不会包含隐藏文件
def count_files_and_size(directory):
    total_files = 0
    total_size = 0

    for p in pathlib.Path(directory).rglob('*'):
        if p.is_file():
            # 增加文件数量
            total_files += 1
            # 增加文件大小
            total_size += p.stat().st_size

    return total_files, total_size

def find_c_files(directory):
    path = pathlib.Path(directory)
    for file in path.glob("**/*.c"):
        yield file


def find_h_files(directory):
    path = pathlib.Path(directory)
    for file in path.glob("**/*.h"):
        yield file


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
        cleaned_text = re.sub(r'\s+', '', text)
        # 统计字符数量
        count += len(cleaned_text)
    return count

# 有这些标识的不进行合并行
_pattern = r'\bif\b|\#|\{|}|\;|\:'
_symbols_pattern = re.compile(_pattern)
def check_symbols(text):
    # 使用 re.search 查找模式
    match = _symbols_pattern.search(text)
    # 如果找到匹配，返回 True；否则返回 False
    return bool(match)


# 单行定义 function 的正则表达式
func_pattern = re.compile( r"^(\w+\s+){1,}(\*?\w+)\(")
inline_func_pattern = re.compile(r"(\S+\s+)*?(=+\s)?(\(.*\)+)?(\*?\w+)\(")
# 找到定义的所有方法，并且统计方法的行数， 统计方法所有的字符数， 统计方法内调用的其他方法
# class_pattern = re.compile(r'^\s*(void\s+)?(static\s+)?(__init\s+)?(.*?)\s+(\w+)')
brace_pattern = re.compile(r'{|}')
remove_string_pattern = re.compile(r'"(.*?)"')
static_pattern = re.compile(r'\bstatic\b')


def extract_c_file(file_path, god_path):
    # empty_line_pattern = re.compile(r'^\s*$')
    # comment_pattern = re.compile(r'/\*.*?\*/|\s*//.*')
    file_path = pathlib.Path(file_path)
    # 读取文件内容
    with open(file_path, 'r', errors='ignore') as file:
        data = file.read()
    # logging.info("开始处理：%s", file_path)

    # 正则表达式匹配多行注释
    data = re.sub(r'/\*.*?\*/', '', data, flags=re.DOTALL)
    # 正则表达式匹配单行注释
    data = re.sub(r'//.*', '', data)
    # 过滤掉空行
    lines = data.splitlines()
    lines = [line for line in lines if line.strip()]

    # 使用正则表达式匹配#include指令后的文件名, 全局
    pattern = r'#include <(.+?)>'
    # 查找所有匹配的文件名， ok
    global_include_match = re.findall(pattern, data)

    # 使用正则表达式匹配#include指令后的文件名, 当前目录
    pattern = r'#include "(.+?)"'
    # 查找所有匹配的文件名， ok
    local_include_match = re.findall(pattern, data)
    local_include_file_path = []
    for path in local_include_match:
        path = file_path.parent.joinpath(path).resolve().absolute()
        local_include_file_path.append(path.as_posix().replace(god_path,""))

    func_list = []
    brace_count = 0
    func_name = None
    func_static = False
    func_start_line = None
    # 存储 funcline， 统计代码长度
    func_code_list = []
    ref_func_name_list = []
    brace_flag = False

    # v2024.02.04, 添加多行合并逻辑，没有出现 #{}; 于下面一行合并
    line_cache = []
    for i, one_line in enumerate(lines):
        # 将引号内的变量替换，防止匹配出错
        line_without_string = remove_string_pattern.sub('"x"', one_line)  
        if check_symbols(line_without_string):
            # 符合断行， 并且没有前行
            if not line_cache:
                line = one_line
            # 符合断行， 并且有前行
            else:
                # 行内如果有 # 或者 } 这个是没有考虑到的
                line_cache.append(one_line)
                line = " ".join(line_cache)
                line_cache = []
        else:
            # 不符合断行, 已到末行
            if i + 1 == len(lines):
                # 有前行， 合并推理
                if line_cache:
                    line_cache.append(one_line)
                    line = " ".join(line_cache)
                else:
                    line = one_line
            # 不符合断行, 加入 line_cache
            else:
                line_cache.append(one_line)
                continue
    
    
        # 合并后的 line,  再次 remove test
        line_without_string = remove_string_pattern.sub('"x"', line)  
        
        # 单行定于函数
        if func_name is None:
            # 查找类定义
            match = func_pattern.match(line)
            if match:
                # expect_1 core_wildfire.c, 排除全局函数调用
                line_without_space = line.replace(" ",'')
                # logging.warning(line_without_space)
                if line_without_space.endswith(");"):
                    # 非函数定义行，也不在函数中
                    pass
                else:
                    func_name = match.group(2)
                    if static_pattern.search(line_without_string):
                        # 静态函数
                        func_static = True
                        
                    func_start_line = i
                    func_code_list.append(line)
                    brace_count = 0  # Reset brace count for new class 
        else:
            func_code_list.append(line)
            
            # if len(line_without_string) > 5000:
            #     logging.info("处理：%s, %s, size: %s", file_path, i, len(line_without_string))
            # 超长的行数过滤掉
            if len(line_without_string) < 2000:
                match_all = inline_func_pattern.findall(line_without_string)
                for match in match_all:
                    ref_func_name = match[3]
                    ref_func_name_list.append(ref_func_name)

        braces = brace_pattern.findall(line_without_string)
        if braces:
            brace_flag = True
            brace_count += braces.count('{')
            brace_count -= braces.count('}')
            
        if braces and brace_count == 0 and func_name is not None:
            # 类定义结束
            func_line_count = i - func_start_line + 2
            func_list.append([func_name, func_line_count, code_str_count(func_code_list),list(ref_func_name_list), func_static])
            func_name = None  # Reset for next class
            func_static = False
            func_code_list = []
            ref_func_name_list = []

    # 最后一个没处理的 func_name
    if func_name:
        func_line_count = i - func_start_line + 2
        func_list.append([func_name, func_line_count, code_str_count(func_code_list),list(ref_func_name_list), func_static])

    # 路径处理
    file_name_str =  file_path.as_posix()
    c_name = file_name_str.replace(god_path,"").split('/')[-1]
    path_out_include = file_name_str.split("include")[-1].strip("/").split("/")[-4:]
    path_name_list = []
    for i in range(len(path_out_include)):
        path_name_list.append("/".join(path_out_include[i:]))
    
    # logging.info("处理完毕：%s", file_path)
    return {
        'c_name': c_name,
        'my_include_name_list': path_name_list,
        'func_data': func_list,
        'file_path': file_path.as_posix().replace(god_path,""),
        'global_include': global_include_match, 
        'local_include': local_include_file_path,
    }
    

def test():
    test_c_path = "/mnt/wd01/github/linux_old1/kernel/kallsyms_selftest.c"
    test_h_path = "/mnt/wd01/github/linux_old1/include/crypto/authenc.h"
    # test_c_path = "/mnt/wd01/github/linux_old1/tools/testing/radix-tree/maple.c"
    test_c_path= "/mnt/wd01/github/linux_old1/arch/alpha/kernel/core_wildfire.c"
    ret = extract_c_file(test_c_path)
    logging.info(ret)
