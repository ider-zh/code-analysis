import unittest
import logging.config
import json
import dictdiffer
import os
from src.protos import text_mate_pb2_grpc
from src.protos import text_mate_pb2
import grpc
from c_formatter_42.run import run_all

# 加载配置文件
logging.config.fileConfig("config/logging.conf")


class MyTestCase(unittest.TestCase):
    def test_start(self):
        print("test ok")

    def test_gprc_server(self):
        
        GRPC_URI= '127.0.0.1:50051'

        text = """
static void test_perf_kallsyms_on_each_match_symbol(void)
{
	u64 t0, t1;
	struct test_stat stat;

	memset(&stat, 0, sizeof(stat));
	stat.max = INT_MAX;
	stat.name = stub_name;
	t0 = ktime_get_ns();
	kallsyms_on_each_match_symbol(match_symbol, stat.name, &stat);
	t1 = ktime_get_ns();
	pr_info("kallsyms_on_each_match_symbol() traverse all: %lld ns", t1 - t0);
}
"""
        # logging.info(text.split('\n'))
        scope = "source.c"
        with grpc.insecure_channel(GRPC_URI) as channel:
            stub = text_mate_pb2_grpc.TextMateServiceStub(channel)
            
            # test_files = ['kallsyms_selftest']
            test_files = ['test']
            for file_name in test_files:
                file_path = f"tests/data/2024/{file_name}.c"
                with open(file_path, "rt") as f:
                    data = f.read()
                data = run_all(data)
                response = stub.GetTextMatePlain(text_mate_pb2.CodeSource(text=data,scope=scope))
                logging.info(response.text)

        # self.assertEqual(ret, new_text)

