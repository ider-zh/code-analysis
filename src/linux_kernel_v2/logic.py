# 继续拆解加速
import time
import pymongo
from pymongo import UpdateMany, UpdateOne
import collections
import re
from multiprocessing.dummy import Pool
import git
import logging.config
import itertools
import functools
import datetime
import pathlib
from tqdm import tqdm
import math

logging.config.fileConfig("config/logging.conf")

from src.linux_kernel_v2.utils import (
    extract_c_file,
    find_c_files,
    find_h_files,
    count_files_and_size,
    find_most_common_parent,
    find_most_common_parent_super,
)


def get_mongo_database():
    # connURI
    database = pymongo.MongoClient("192.168.50.2").linux_kernel
    return database


# 从项目文件中提取源文件的link，并缓存的 database
def get_temporary_mongo_database():
    # connURI
    database = pymongo.MongoClient("127.0.0.1", 37017).get_database("linux_temporary")
    return database


def c_link_h(c_object, h_includeName_filePath_map, h_file_map):
    """一般是.h .c一一对应， 同名同层级的可以一对多"""
    ret = []
    c_name = re.sub(r"\.c$", "", c_object["c_name"])
    for local_h_path in c_object["local_include"]:
        h_name = re.sub(r"\.h$", "", local_h_path.split("/")[-1])
        if c_name == h_name:
            # match 成功
            if local_h_path in h_file_map:
                ret.append(local_h_path)
    if ret:
        return ret

    for global_h_path in c_object["global_include"]:
        h_name = re.sub(r"\.h$", "", global_h_path.split("/")[-1])
        if c_name == h_name:
            # match 成功
            if global_h_path in h_includeName_filePath_map:
                ret.extend(h_includeName_filePath_map[global_h_path])
    return ret


def extract_ref_from_repo_or_cache(project_path, year, version):
    database = get_temporary_mongo_database()
    # todo
    # version = "v4"
    collection_name = f"{pathlib.Path(project_path).name}_{year}_{version}"

    collection = database.get_collection(collection_name)

    index_list = collection.list_indexes()
    if "createdAt" not in index_list:
        collection.create_index({"createdAt": 1}, expireAfterSeconds=60 * 60 * 24 * 15)
        logging.info("create create TTL index")

    c_data_out = []
    h_data_out = []
    global_include_name_mapping = collections.defaultdict(list)
    file_path_obj_mapping = dict()

    for doc in collection.find({"file_type": "c"}):
        del doc["_id"]
        del doc["createdAt"]
        c_data_out.append(doc)
        file_path_obj_mapping[doc["file_path"]] = doc
        # 全局路径中可能的名字，这部分会存在过多的引用
        for package_name in doc["my_include_name_list"]:
            global_include_name_mapping[package_name].append(doc)

    for doc in collection.find({"file_type": "h"}):
        del doc["_id"]
        del doc["createdAt"]
        h_data_out.append(doc)
        file_path_obj_mapping[doc["file_path"]] = doc
        # 全局路径中可能的名字，这部分会存在过多的引用
        for package_name in doc["my_include_name_list"]:
            global_include_name_mapping[package_name].append(doc)

    if len(c_data_out) > 0 and len(h_data_out) > 0:
        return (
            c_data_out,
            h_data_out,
            global_include_name_mapping,
            file_path_obj_mapping,
        )

    # extract data from repo
    logging.info("start to extract file")

    with Pool(10) as p:
        c_data_out = p.starmap(
            extract_c_file,
            [
                (file_path, project_path, i)
                for i, file_path in enumerate(find_c_files(project_path))
            ],
            chunksize=10,
        )
        logging.info("c file submit complete")
        h_data_out = p.starmap(
            extract_c_file,
            [
                (file_path, project_path, i)
                for i, file_path in enumerate(find_h_files(project_path))
            ],
            chunksize=10,
        )
        logging.info("h file submit complete")

    logging.info("c file count: %d, h file count %d", len(c_data_out), len(h_data_out))

    logging.info("global_include_name_mapping start")
    # 建立 golbal_incude 的 maping
    for obj in itertools.chain(c_data_out, h_data_out):
        # 所有 对象的文件路径映射
        file_path_obj_mapping[obj["file_path"]] = obj
        # 全局路径中可能的名字，这部分会存在过多的引用
        for package_name in obj["my_include_name_list"]:
            global_include_name_mapping[package_name].append(obj)

    # 将每个h的引入树形遍历，补全引入的tree，
    # 要有从 .h 找到 .c 的索引， 也要有 .c 找到 .h 的索引

    now = datetime.datetime.now()
    doc_list = []
    for i, doc in enumerate(c_data_out):
        doc["file_type"] = "c"
        doc["createdAt"] = now
        doc_list.append(doc)
        if (i + 1) % 10_000 == 0:
            collection.insert_many(doc_list)
            doc_list = []

    for i, doc in enumerate(h_data_out):
        doc["file_type"] = "h"
        doc["createdAt"] = now
        doc_list.append(doc)
        if (i + 1) % 10_000 == 0:
            collection.insert_many(doc_list)
            doc_list = []

    if doc_list:
        collection.insert_many(doc_list)
        doc_list = []

    logging.info("global_include_name_mapping complete")

    return c_data_out, h_data_out, global_include_name_mapping, file_path_obj_mapping


def pipe_handle(project_path, year, version):

    c_data_out, h_data_out, global_include_name_mapping, file_path_obj_mapping = (
        extract_ref_from_repo_or_cache(project_path, year, version)
    )
    # 提取并且格式化后的 file object

    logging.info("func include extend start")

    @functools.lru_cache(1_000_000)
    def deep_ref_scan(file_path):

        obj = file_path_obj_mapping[file_path]
        ref_out_obj_file_path = []
        func_name_list = set()

        for include_name in obj["local_include"]:
            if ref_obj := file_path_obj_mapping.get(include_name):
                ref_out_obj_file_path.append(ref_obj["file_path"])

        for include_name in obj["global_include"]:
            if ref_obj_list := global_include_name_mapping.get(include_name):
                ref_out_obj_file_path.extend(
                    [item["file_path"] for item in ref_obj_list]
                )

        for func_data in obj["func_data"]:
            # if not func_data[4]:
            # disable
            # position 4 is static flag, 非 static
            func_name_list.add(func_data[0])

        return ref_out_obj_file_path, func_name_list

    project_h_ref_tree_mapping = collections.defaultdict(lambda: {})
    # 找到 obj 的所有 include 以及其定义的 func
    for obj in h_data_out:
        obj_file_path = obj["file_path"]
        todo_pool = set([obj_file_path])
        complete_pool = set()
        while todo_pool:
            file_path = todo_pool.pop()
            ref_out_obj_file_path, func_name_list = deep_ref_scan(file_path)
            if func_name_list:
                project_h_ref_tree_mapping[obj_file_path][file_path] = func_name_list
            complete_pool.add(file_path)

            for task_path in ref_out_obj_file_path:
                if task_path not in complete_pool:
                    todo_pool.add(task_path)

    # complete project_h_ref_tree_mapping
    logging.info("func include extend complete")
    # clear lru cache
    deep_ref_scan.cache_clear()

    logging.info("func_link_h_to_c start")
    # 从 h 文件，找到 .c 文件中对应的方法
    func_link_h_to_c = collections.defaultdict(list)
    for obj in c_data_out:
        obj_file_path = obj["file_path"]
        func_name_set = set()
        for item in obj["func_data"]:
            # 非 static
            if not item[4]:
                func_name_set.add(item[0])

        if not func_name_set:
            # 没有可以被外部引用的 func, .c 文件
            continue

        # 遍历其 ref， 找到同名的 func
        # 合并 include 集合
        include_dict = dict()
        for include_name in obj["local_include"]:
            if ref_obj := file_path_obj_mapping.get(include_name):
                h_path = ref_obj["file_path"]
                if h_path in project_h_ref_tree_mapping:
                    include_dict.update(project_h_ref_tree_mapping[h_path])

        for include_name in obj["global_include"]:
            if ref_obj_list := global_include_name_mapping.get(include_name):
                for ref_obj in ref_obj_list:
                    h_path = ref_obj["file_path"]
                    if h_path in project_h_ref_tree_mapping:
                        include_dict.update(project_h_ref_tree_mapping[h_path])

        # 将 .h 文件的 func ref 到 .c 文件
        for h_path, func_set in include_dict.items():
            func_intersection = func_name_set & func_set
            # links
            for func_name in func_intersection:
                func_link_h_to_c[(h_path, func_name)].append(obj_file_path)

    logging.info("func_link_h_to_c complete")

    # 建立项目 ID
    GLOBAL_FUNC_ID = 0
    MASTER_FUNC_MAP = {}
    for item in c_data_out:
        file_path = item["file_path"]

        for [func_name, lineCount, strCount, linksOut_list, func_static] in item[
            "func_data"
        ]:
            key = (file_path, func_name)
            MASTER_FUNC_MAP[key] = {
                "_id": GLOBAL_FUNC_ID,
                "func_path": file_path,
                "static": func_static,
                "func_name": func_name,
                "line_count": lineCount,
                "str_count": strCount,
                "linksIn_id_list": [],
                "linksOut_func_list": linksOut_list,
            }
            GLOBAL_FUNC_ID += 1
    logging.info("MASTER_FUNC_MAP length: %d", len(MASTER_FUNC_MAP))

    import pdb

    # pdb.set_trace()

    logging.info("func mapping start")
    time_start = time.time()
    # 可以干活了， 将 .c 文件的 func 映射到 .h 文件
    for obj in c_data_out:
        # 先是判断内部 ref
        file_path = obj["file_path"]
        self_func_name_set = set()
        for item in obj["func_data"]:
            self_func_name_set.add(item[0])

        if not self_func_name_set:
            continue

        # 合并 include 集合
        include_dict = dict()
        for include_name in obj["local_include"]:
            if ref_obj := file_path_obj_mapping.get(include_name):
                h_path = ref_obj["file_path"]
                if h_path in project_h_ref_tree_mapping:
                    include_dict.update(project_h_ref_tree_mapping[h_path])

        for include_name in obj["global_include"]:
            if ref_obj_list := global_include_name_mapping.get(include_name):
                for ref_obj in ref_obj_list:
                    h_path = ref_obj["file_path"]
                    if h_path in project_h_ref_tree_mapping:
                        include_dict.update(project_h_ref_tree_mapping[h_path])

        # 反转 include_dict
        reverse_include_dict = collections.defaultdict(set)
        for h_path, func_name_list in include_dict.items():
            for func_name in func_name_list:
                reverse_include_dict[func_name].update(h_path)

        for item in obj["func_data"]:
            func_name = item[0]
            source_func_key = (file_path, func_name)
            source_func_id = MASTER_FUNC_MAP.get(source_func_key, {})["_id"]
            # if not source_func_id:
            # invitably occurring
            #     logging.warning("source_func_key miss:%s", source_func_key)
            #     continue

            for ref_func_name in item[3]:
                if ref_func_name in self_func_name_set:
                    # 内部 call
                    target_func_key = (file_path, ref_func_name)
                    MASTER_FUNC_MAP[target_func_key]["linksIn_id_list"].append(
                        source_func_id
                    )
                else:
                    # 外部 call
                    if h_path_list := reverse_include_dict.get(ref_func_name):
                        for h_path in h_path_list:
                            key = (h_path, ref_func_name)
                            for c_obj_path in func_link_h_to_c.get(key, []):
                                target_func_key = (c_obj_path, ref_func_name)
                                MASTER_FUNC_MAP[target_func_key][
                                    "linksIn_id_list"
                                ].append(source_func_id)

    # pdb.set_trace()

    database = get_mongo_database()
    collection = database[f"func_graph_{version}_{year}"]
    collection.drop()
    collection.create_index(
        [
            ("func_path", pymongo.DESCENDING),
            ("func_name", pymongo.DESCENDING),
            ("static", pymongo.DESCENDING),
        ],
        background=True,
    )

    collection.create_index(
        [("func_name", pymongo.DESCENDING)],
        background=True,
    )
    # 将数据存储到数据库
    i = 0
    doc_list = []
    for doc in MASTER_FUNC_MAP.values():
        doc_list.append(doc)
        i += 1
        if i > 10000:
            collection.insert_many(doc_list)
            doc_list = []
            i = 0
    if doc_list:
        collection.insert_many(doc_list)

    logging.info("已完成：%d, 耗时：%d", i, int(time.time() - time_start))


def pipe_handle_v2(project_path, year, version):
    """
    include 采用就近原则，没有接近的就用全量"""
    # c_data_out: store c file object 的 list
    # h_data_out: store h file object list
    # global_include_name_mapping： include name map the file object
    # file_path_obj_mapping： file path map the object
    c_data_out, h_data_out, global_include_name_mapping, file_path_obj_mapping = (
        extract_ref_from_repo_or_cache(project_path, year, version)
    )

    # 提取并且格式化后的 file object
    logging.info("h map to c start")

    # 引用关系建立法则
    # 1. 首先找 local function and macro
    # 2.

    # 将所有的 c func ref 到 include 的 h file
    # 如果是 static ，就不 ref
    # 将 c 中的 function 注册到自身 include 的 .h 文件上
    h_file_mapping_c_func = collections.defaultdict(
        lambda: collections.defaultdict(list)
    )
    for obj in c_data_out:
        obj_file_path = obj["file_path"]
        ref_out_obj_file_path = []

        for include_name in obj["local_include"]:
            if ref_obj := file_path_obj_mapping.get(include_name):
                ref_out_obj_file_path.append(ref_obj["file_path"])

        for include_name in obj["global_include"]:
            if ref_obj_list := global_include_name_mapping.get(include_name):
                # 从中找出路径最近的 include, 最好只 include 一个
                global_include_path_list = [item["file_path"] for item in ref_obj_list]
                # 相同的 include name 只添加距离最近的 h file
                ref_out_obj_file_path.extend(
                    find_most_common_parent(obj_file_path, global_include_path_list)
                )

        # func_data 会有重名，多重定义，这里只保留第一次实现和声明
        func_set = set()
        for func_data in obj["func_data"]:

            if func_data[0] in func_set:
                continue
            func_set.add(func_data[0])

            if not func_data[4]:
                for ref_h_file_path in ref_out_obj_file_path:
                    # 只要根据头文件，就能找到其包含的函数
                    h_file_mapping_c_func[ref_h_file_path][func_data[0]].append(
                        obj_file_path
                    )

    logging.info("h map to c complete")

    @functools.lru_cache(1_000_000)
    def deep_ref_scan(obj_file_path):

        obj = file_path_obj_mapping[obj_file_path]
        # 所有 include 的 h_path
        ref_out_obj_file_path = []
        func_name_set = set()
        macro_set = set()
        for include_name in obj["local_include"]:
            if ref_obj := file_path_obj_mapping.get(include_name):
                ref_out_obj_file_path.append(ref_obj["file_path"])

        for include_name in obj["global_include"]:
            if ref_obj_list := global_include_name_mapping.get(include_name):
                global_include_path_list = [item["file_path"] for item in ref_obj_list]
                # 相同的 include name 只添加距离最近的 h file
                ref_out_obj_file_path.extend(
                    find_most_common_parent(obj_file_path, global_include_path_list)
                )

        for func_data in obj["func_data"]:
            func_name_set.add(func_data[0])

        for func_data in obj["macro_list"]:
            macro_set.add(func_data)

        # extend func
        # if file_path in h_file_mapping_c_func:
        #     func_name_set.update(h_file_mapping_c_func[file_path])

        return set(ref_out_obj_file_path), func_name_set, macro_set

    logging.info("func include extend complete")
    project_h_ref_tree_mapping = collections.defaultdict(lambda: {})
    # 找到 obj 的所有 include 以及其定义的 func
    # 将 h 头文件所 include 的其他
    for obj in h_data_out:
        obj_file_path = obj["file_path"]
        todo_pool = set([obj_file_path])
        complete_pool = set()
        while todo_pool:
            todo_file_path = todo_pool.pop()
            # 返回 f file 里递归引用的头文件， 还有 h file 声明的 func
            ref_out_obj_file_path, func_name_set, macro_set = deep_ref_scan(
                todo_file_path
            )
            if func_name_set or macro_set:
                project_h_ref_tree_mapping[obj_file_path][todo_file_path] = [
                    func_name_set,
                    macro_set,
                ]
            complete_pool.add(todo_file_path)

            for task_path in ref_out_obj_file_path:
                if task_path not in complete_pool:
                    todo_pool.add(task_path)

    # complete project_h_ref_tree_mapping
    logging.info("func include extend complete")
    # clear lru cache
    deep_ref_scan.cache_clear()

    # logging.info("func_link_h_to_c start")

    # 从 h 文件，找到 .c 文件中对应的方法
    # func_link_h_to_c = collections.defaultdict(list)
    # for obj in c_data_out:
    #     obj_file_path = obj["file_path"]
    #     func_name_set = set()
    #     for item in obj["func_data"]:
    #         # 非 static
    #         if not item[4]:
    #             func_name_set.add(item[0])

    #     if not func_name_set:
    #         # 没有可以被外部引用的 func, .c 文件
    #         continue

    #     # 遍历其 ref， 找到同名的 func
    #     # 合并 include 集合
    #     include_dict = dict()
    #     for include_name in obj["local_include"]:
    #         if ref_obj := file_path_obj_mapping.get(include_name):
    #             h_path = ref_obj["file_path"]
    #             if h_path in project_h_ref_tree_mapping:
    #                 include_dict.update(project_h_ref_tree_mapping[h_path])

    #     for include_name in obj["global_include"]:
    #         if ref_obj_list := global_include_name_mapping.get(include_name):
    #             global_include_path_list = [item["file_path"] for item in ref_obj_list]
    #             # 相同的 include name 只添加距离最近的 h file
    #             ref_obj_path_list = find_most_common_parent(
    #                 obj_file_path, global_include_path_list
    #             )
    #             for h_path in ref_obj_path_list:
    #                 if h_path in project_h_ref_tree_mapping:
    #                     include_dict.update(project_h_ref_tree_mapping[h_path])

    #     # 将 .h 文件的 func ref 到 .c 文件
    #     for h_path, func_set in include_dict.items():
    #         func_intersection = func_name_set & func_set
    #         # links
    #         for func_name in func_intersection:
    #             func_link_h_to_c[(h_path, func_name)].append(obj_file_path)

    # logging.info("func_link_h_to_c complete")

    # 建立项目 ID
    GLOBAL_FUNC_ID = 0
    MASTER_FUNC_MAP = {}
    for item in c_data_out:
        obj_file_path = item["file_path"]

        # func 去重，只保留第一个
        func_set = set()
        for [func_name, lineCount, strCount, linksOut_list, func_static] in item[
            "func_data"
        ]:

            if func_name in func_set:
                continue
            func_set.add(func_name)

            key = (obj_file_path, func_name)
            MASTER_FUNC_MAP[key] = {
                "_id": GLOBAL_FUNC_ID,
                "func_path": obj_file_path,
                "static": func_static,
                "func_name": func_name,
                "line_count": lineCount,
                "str_count": strCount,
                "_linksOut_func_id_list": [],
                "_linksOut_macro_list": [],
                "_linksOut_miss_list": [],
                "_confuse_linksOut_func_list": [],
                "linksOut_func_list": linksOut_list,
            }
            GLOBAL_FUNC_ID += 1

    logging.info("MASTER_FUNC_MAP length: %d", len(MASTER_FUNC_MAP))

    import pdb

    # pdb.set_trace()

    logging.info("func mapping start")
    time_start = time.time()
    # 可以干活了， 将 .c 文件的 func 映射到 .h 文件
    for obj in tqdm(c_data_out):
        # 先是判断内部 ref

        obj_file_path = obj["file_path"]
        self_func_name_set = set()
        self_macro_set = set()

        for item in obj["macro_list"]:
            self_macro_set.add(item[0])

        for [func_name, lineCount, strCount, linksOut_list, func_static] in obj[
            "func_data"
        ]:
            self_func_name_set.add(func_name)

        # 排除没有 func 的 .c
        if not self_func_name_set:
            continue

        # todo
        # 需要 map 的 out 函数
        # call_func_set
        # hfile 里包含的 func， 以及其定义的 path
        # h_file_mapping_c_func[ref_h_file_path][func_data[0]].append(
        #     obj_file_path
        # )
        # 一个 h file， 包含的多个 h file
        # project_h_ref_tree_mapping

        # 获得所有的 include name, 作为寻找最接近c函数的一个优先权重
        include_name_set = set()

        # 合并 include 集合
        # project_h_ref_tree_mapping[obj_file_path][file_path] = [func_name_list,macro_set]
        include_dict = dict()
        for include_name in obj["local_include"]:
            include_name_set.add(include_name.split("/")[-1].split(".")[0])

            if ref_obj := file_path_obj_mapping.get(include_name):
                h_path = ref_obj["file_path"]
                if h_path in project_h_ref_tree_mapping:
                    include_dict.update(project_h_ref_tree_mapping[h_path])

        for include_name in obj["global_include"]:
            this_include_name = include_name.split("/")[-1].split(".")[0]
            include_name_set.add(this_include_name)

            if ref_obj_list := global_include_name_mapping.get(include_name):
                # 从中找出路径最近的 include, 最好只 include 一个
                global_include_path_list = [item["file_path"] for item in ref_obj_list]
                # 相同的 include name 只添加距离最近的 h file

                # 优先根据 include name, 所有的 h.name 必定和 include name 编辑距离为0
                for h_path in find_most_common_parent(
                    obj_file_path, global_include_path_list
                ):
                    if h_path in project_h_ref_tree_mapping:
                        include_dict.update(project_h_ref_tree_mapping[h_path])

        # 反转 include_dict
        reverse_include_dict = collections.defaultdict(set)
        link_macro_set = set()
        for h_path, [func_name_list, macro_set] in include_dict.items():
            link_macro_set.update(macro_set)
            if func_name_source_map := h_file_mapping_c_func.get(h_path):
                for func_name, func_source_list in func_name_source_map.items():
                    reverse_include_dict[func_name].update(func_source_list)

        # 进行比对处理
        out_func_name_cache = {}
        out_confuse_func_name_cache = collections.defaultdict(list)

        func_set = set()
        for [func_name, lineCount, strCount, linksOut_list, func_static] in obj[
            "func_data"
        ]:
            if func_name in func_set:
                continue
            func_set.add(func_name)

            source_func_key = (obj_file_path, func_name)
            # source_func_id = MASTER_FUNC_MAP.get(source_func_key, {})["_id"]
            source_func_obj = MASTER_FUNC_MAP[source_func_key]
            confuse_data_map = collections.defaultdict(int)

            out_macro_set = set()
            out_miss_set = set()
            # _linksOut_macro_list
            # _linksOut_miss_list
            for ref_func_name in linksOut_list:

                # 缓存加速
                if target_func_id := out_func_name_cache.get(ref_func_name):
                    source_func_obj["_linksOut_func_id_list"].append(target_func_id)
                    continue
                if target_func_key_list := out_confuse_func_name_cache.get(
                    ref_func_name
                ):
                    for target_func_key in target_func_key_list:
                        confuse_data_map[target_func_key] += 1
                    continue

                if ref_func_name in self_func_name_set:
                    # 内部 call
                    target_func_key = (obj_file_path, ref_func_name)
                    target_func_id = MASTER_FUNC_MAP[target_func_key]["_id"]
                    source_func_obj["_linksOut_func_id_list"].append(target_func_id)
                    out_func_name_cache[ref_func_name] = target_func_id

                elif ref_func_name in self_macro_set:
                    out_macro_set.add(ref_func_name)
                    continue
                else:
                    # 外部 call
                    if h_path_list := reverse_include_dict.get(ref_func_name):

                        # 找到最近的 n 个
                        # todo
                        # 相同的 include name 只添加距离最近的 h file
                        out_func_c_path_list = find_most_common_parent_super(
                            obj_file_path, h_path_list, include_name_set
                        )
                        if len(out_func_c_path_list) == 1:
                            target_func_key = (
                                out_func_c_path_list.pop(),
                                ref_func_name,
                            )
                            target_func_id = MASTER_FUNC_MAP[target_func_key]["_id"]
                            source_func_obj["_linksOut_func_id_list"].append(
                                target_func_id
                            )
                            out_func_name_cache[ref_func_name] = target_func_id
                        elif len(out_func_c_path_list) > 1:
                            # 一对多的引出
                            for c_obj_path in out_func_c_path_list:
                                target_func_key = (c_obj_path, ref_func_name)
                                target_func_id = MASTER_FUNC_MAP[target_func_key]["_id"]

                                confuse_func_key = (target_func_id, c_obj_path)

                                confuse_data_map[confuse_func_key] += 1

                                out_confuse_func_name_cache[ref_func_name].append(
                                    confuse_func_key
                                )
                    elif ref_func_name in link_macro_set:
                        out_macro_set.add(ref_func_name)
                    else:
                        out_miss_set.add(ref_func_name)

            for key, value in confuse_data_map.items():
                source_func_obj["_confuse_linksOut_func_list"].append(
                    {"p": key[1], "i": key[0], "c": value, "n": ref_func_name}
                )
            source_func_obj["_linksOut_macro_list"] = list(out_macro_set)
            source_func_obj["_linksOut_miss_list"] = list(out_miss_set)
            # if len(source_func_obj["_confuse_linksOut_func_list"]) > 0:
            #     pdb.set_trace()
    # pdb.set_trace()

    # last confuse handle

    for doc in MASTER_FUNC_MAP.values():
        # if doc["static"]:
        #     continue
        if not doc["_confuse_linksOut_func_list"]:
            doc["linksOut_func_id_list"] = doc["_linksOut_func_id_list"]
        else:
            group = collections.defaultdict(list)
            for item in doc["_confuse_linksOut_func_list"]:
                group[item["n"]].append(item)
            confuse_top_doc_list = get_top_confuse_value(group.values())

            linksOut_func_id_list = doc["_linksOut_func_id_list"].copy()
            for item in confuse_top_doc_list:
                for _ in range(item["c"]):
                    linksOut_func_id_list.append(item["i"])

            doc["linksOut_func_id_list"] = linksOut_func_id_list

    database = get_mongo_database()
    collection = database[f"func_graph_{version}_{year}"]
    collection.drop()
    collection.create_index(
        [
            ("func_path", pymongo.DESCENDING),
            ("func_name", pymongo.DESCENDING),
            ("static", pymongo.DESCENDING),
        ],
        background=True,
    )

    collection.create_index(
        [("func_name", pymongo.DESCENDING)],
        background=True,
    )
    # 将数据存储到数据库
    i = 0
    doc_list = []
    for doc in MASTER_FUNC_MAP.values():
        doc_list.append(doc)
        i += 1
        if i > 10000:
            collection.insert_many(doc_list)
            doc_list = []
            i = 0
    if doc_list:
        collection.insert_many(doc_list)

    logging.info("已完成：%d, 耗时：%d", i, int(time.time() - time_start))


def get_top_confuse_value(confuse_list):

    # 定义自定义排序键函数
    def sort_key(path):
        parts = path["p"].split("/")[:-1]
        return parts

    # 使用自定义排序键函数进行排序
    ret = []
    for item_list in confuse_list:
        item_list = sorted(item_list, key=sort_key)
        ret.append(item_list[0])

    return ret


def confuse_handle(version):
    # 只处理 _confuse_linksOut_func_list， 不处理 _linksOut_miss_list。
    # 选择哪个， 按目录首字母排序

    database = get_mongo_database()
    now = datetime.datetime.now()

    for year in range(now.year, 2000, -1):

        result_data_pool = []
        confuse_doc_collects = []
        id_map_funcName = {}

        collection = database[f"func_graph_{version}_{year}"]
        logging.info("start: %s", year)

        for doc in collection.find():
            if doc["static"]:
                continue

            id_map_funcName[doc["_id"]] = doc["func_name"]

            if not doc["_confuse_linksOut_func_list"]:
                if doc["_linksOut_func_id_list"]:
                    result_data_pool.append(
                        UpdateOne(
                            {"_id": doc["_id"]},
                            {
                                "$set": {
                                    "linksOut_func_id_list": doc[
                                        "_linksOut_func_id_list"
                                    ],
                                }
                            },
                        )
                    )
            else:
                # handle confuse
                confuse_doc_collects.append(doc)

        for doc in confuse_doc_collects:
            group = collections.defaultdict(list)
            for item in doc["_confuse_linksOut_func_list"]:
                if (s_func_name := id_map_funcName.get(item["i"], None)) != None:
                    group[s_func_name].append(item)
            confuse_top_doc_list = get_top_confuse_value(group.values())

            for item in confuse_top_doc_list:
                for _ in range(item["c"]):
                    doc["_linksOut_func_id_list"].append(item["i"])
            result_data_pool.append(
                UpdateOne(
                    {"_id": doc["_id"]},
                    {
                        "$set": {
                            "linksOut_func_id_list": doc["_linksOut_func_id_list"],
                        }
                    },
                )
            )

        batch_size = 10000

        # 计算需要多少批次
        num_batches = math.ceil(len(result_data_pool) / batch_size)

        # 对更新操作列表进行分批
        for batch_num in range(num_batches):
            start_idx = batch_num * batch_size
            end_idx = min((batch_num + 1) * batch_size, len(result_data_pool))
            batch_operations = result_data_pool[start_idx:end_idx]

            # 执行批量写入操作
            result = collection.bulk_write(batch_operations, ordered=False)
            logging.info(f"Batch {batch_num+1}/{num_batches}: {result.bulk_api_result}")


def scan_commit(commit_version, repo):
    try:
        result = repo.git.checkout(commit_version, force=True)
        logging.info("checkout to version: %s", commit_version)
    except git.exc.GitCommandError as e:
        if "File name too long" in str(e):
            # 处理 File name too long 异常
            logging.warning(
                f" {commit_version.hexsha}, Caught File name too long error: {e}"
            )
            return
        elif (
            "Please commit your changes or stash them before you switch branches"
            in str(e)
        ):
            repo.git.checkout("-b", "tmp")
            repo.git.stash()
            result = repo.git.checkout(commit_version, force=True)
            logging.warning(
                "Please commit your changes or stash them before you switch branches"
            )
        else:
            logging.exception(e)
            logging.warning(f"{commit_version.hexsha}, un handle error")
            # 将其他异常继续向上抛出
            raise e
    # checkout 已经完成了， 现在需要 scan code


def git_histroy_review(project_source_path, version):

    repo = git.Repo(project_source_path)

    branch_list = []
    logging.info("start to find mastetr branch")
    for branch in repo.remotes[0].fetch():
        branch_list.append([branch, len(list(repo.iter_commits(branch.name)))])
    master_branch = branch_list[0][0]

    year_dict = collections.defaultdict(list)

    logging.info("start to get all commit")
    for commit in repo.iter_commits(master_branch.name):
        committed_datetime = commit.committed_datetime
        year_str = committed_datetime.year
        year_dict[year_str].append(commit)

    logging.info("start to get all commit by year")
    year_commit_dict = {}
    for year_str, commit_list in year_dict.items():
        commit_list.sort(key=lambda x: x.committed_datetime, reverse=True)
        year_commit_dict[year_str] = commit_list[0]

    database = get_mongo_database()
    repo_stats_collection = database[f"repo_stats_{version}"]

    for year_str, commit in year_commit_dict.items():
        # if year_str > 2020:
        #     continue
        logging.info("start: %s", year_str)
        scan_commit(commit, repo)

        pipe_handle(project_source_path, year_str, version)
        logging.info("scan complete: %s", year_str)

        total_files, total_size = count_files_and_size(project_source_path)
        repo_stats_collection.update_one(
            {"_id": year_str},
            {"$set": {"count": total_files, "size": total_size}},
            upsert=True,
        )


def cache_git_histroy_review(project_source_path, version):

    database = get_mongo_database()
    repo_stats_collection = database[f"repo_stats_{version}"]
    now = datetime.datetime.now()

    for year in range(now.year, 2000, -1):
        year_str = year
        # if year_str > 2020:
        #     continue
        logging.info("start: %s", year_str)
        try:

            pipe_handle_v2(project_source_path, year_str, version)
            logging.info("scan complete: %s", year_str)
        except Exception as e:
            logging.exception(e)
            logging.info("cache repo handle over, end year is: %s", year_str)
            return

        total_files, total_size = count_files_and_size(project_source_path)
        repo_stats_collection.update_one(
            {"_id": year_str},
            {"$set": {"count": total_files, "size": total_size}},
            upsert=True,
        )


def year_review(project_source_path, version, year_str, database=None):
    if not database:
        database = get_mongo_database()
    repo_stats_collection = database[f"repo_stats_{version}"]

    logging.info("start: %s", year_str)
    try:

        pipe_handle_v2(project_source_path, year_str, version)
        logging.info("scan complete: %s", year_str)
    except Exception as e:
        logging.exception(e)
        logging.info("cache repo handle over, end year is: %s", year_str)
        return

    total_files, total_size = count_files_and_size(project_source_path)
    repo_stats_collection.update_one(
        {"_id": year_str},
        {"$set": {"count": total_files, "size": total_size}},
        upsert=True,
    )


# 只是单纯的从代码仓库中提取数据到数据库
def repo_history_extract_cache(project_source_path, version):

    database = get_mongo_database()
    repo_stats_collection = database[f"repo_stats_{version}"]

    repo = git.Repo(project_source_path)
    branch_list = []
    logging.info("start to find mastetr branch")
    for branch in repo.remotes[0].fetch():
        branch_list.append([branch, len(list(repo.iter_commits(branch.name)))])
    master_branch = branch_list[0][0]

    year_dict = collections.defaultdict(list)

    logging.info("start to get all commit")
    for commit in repo.iter_commits(master_branch.name):
        committed_datetime = commit.committed_datetime
        year_str = committed_datetime.year
        year_dict[year_str].append(commit)

    logging.info("start to get all commit by year")
    year_commit_dict = {}
    for year_str, commit_list in year_dict.items():
        commit_list.sort(key=lambda x: x.committed_datetime, reverse=True)
        year_commit_dict[year_str] = commit_list[0]

    database = get_mongo_database()
    repo_stats_collection = database[f"repo_stats_{version}"]

    for year_str, commit in year_commit_dict.items():
        # if year_str >= 2024:
        #     continue
        logging.info("start: %s", year_str)
        scan_commit(commit, repo)
        try:
            extract_ref_from_repo_or_cache(project_source_path, year_str, version)
        except Exception as e:
            logging.exception(e)
            logging.info("cache repo handle over, end year is: %s", year_str)
            return

        logging.info("scan complete: %s", year_str)

        total_files, total_size = count_files_and_size(project_source_path)
        repo_stats_collection.update_one(
            {"_id": year_str},
            {"$set": {"count": total_files, "size": total_size}},
            upsert=True,
        )


def test_link_linux_kernel(project_source_path):

    pipe_handle(project_source_path, "test", "test")
    # logging.info("scan complete: %s", year_str)


def linux_kernel_commit_history_load(project_source_path):

    repo = git.Repo(project_source_path)

    database = get_mongo_database()
    repo_commit_log_collection = database[f"repo_commit_log"]

    for i, commit in enumerate(repo.iter_commits("master")):
        repo_commit_log_collection.update_one(
            {"_id": str(commit)},
            {
                "$set": {
                    "author_email": commit.author.email,
                    "author_name": commit.author.name,
                    "committed_datetime": commit.committed_datetime,
                    "size": commit.size,
                    "summary": commit.summary,
                    "message": commit.message,
                    "stats_files": commit.stats.files,
                    "stats_total": commit.stats.total,
                }
            },
            upsert=True,
        )
