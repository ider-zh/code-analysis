import unittest
import logging.config
import json
import dictdiffer
import os
from src.linux_kernel_v2.utils import (
    extract_c_file,
)

# 加载配置文件
logging.config.fileConfig("config/logging.conf")


god_path = os.getcwd() + "/tests/data/2024/"


class MyTestCase(unittest.TestCase):
    def test_start(self):
        print("test ok")

    # def test_remove_string_pattern(self):
    #     text = """print("adaffa", "gsaeafa", len([1,2,3,"aabbcc,\'aaa\',ffff"]))"""
    #     ret = 'print("x", "x", len([1,2,3,"x"]))'
    #     new_text = remove_string_pattern.sub('"x"', text)
    #     self.assertEqual(ret, new_text)

    def test_func_pattern(self):
        pass
    
    # def test_check_symbols(self):
    #     test_text = ["if()","ad;","#dada","dada{","dada}","{","aaifda"]
    #     answer = [True,True,True,True,True,True,False]
    #     for i, text in enumerate(test_text):
    #         ret = check_symbols(text)
    #         self.assertEqual(ret, answer[i])


#     def test_inline_func_pattern(self):
#         test_lines = [
# '	pr_info("|---------------------------------------------------------|\n");',
# '	ratio = (u32)div_u64(10000ULL * total_size, total_len);',
# '	pr_info("| %10d |    %10d   |   %10d  |  %2d.%-2d   |\n",',
# '	pr_info("x", stat.min, stat.max, div_u64(stat.sum, stat.real_cnt));',
# '	if (!WILDFIRE_PCA_EXISTS(qbbno, pcano))	    return;'
#         ]
#         ret = [
#             ['pr_info'],
#             ['div_u64'],
#             ['pr_info'],
#             ['pr_info','div_u64'],
#             ['WILDFIRE_PCA_EXISTS']
#         ]
#         for i, line in enumerate(test_lines):
#             new_line = remove_string_pattern.sub('"x"', line)
#             match_all = inline_func_pattern.findall(new_line)
#             ref_func_name_list = []
#             for match in match_all:
#                 ref_func_name = match[3]
#                 ref_func_name_list.append(ref_func_name)
#                 # logging.warning("test match:%s",ref_func_name)
#             self.assertListEqual(ref_func_name_list, ret[i])

    def test_linux_func_extract_1(self):
        print("test ok")
        test_files = ['kallsyms_selftest','core_wildfire']
        # test_files = []
        for file_name in test_files:

            file_path = f"tests/data/2024/{file_name}.c"
            json_path = f"tests/data/2024/{file_name}.json"

            ret = extract_c_file(file_path, god_path)
            with open(json_path, "rt") as f:
                data = json.load(f)

            diff = list(dictdiffer.diff(first=data, second=ret))
            for diff_item in diff:
                logging.warning("%s: %s",file_name, diff_item)
            # self.assertDictEqual(data,ret)
            self.assertEqual(len(diff), 0)
        # logging.info(ret)
