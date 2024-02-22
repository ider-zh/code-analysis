# 继续拆解加速
import time
import pymongo
from pymongo import UpdateMany
from multiprocessing import Process, Queue
import collections
import re
from multiprocessing.dummy import Pool
import git
import logging.config
import itertools
import functools

logging.config.fileConfig('config/logging.conf')

from src.linux_kernel_v2.utils import (
    extract_c_file,
    find_c_files,
    find_h_files,
    count_files_and_size
)

def get_mongo_database():
    # connURI
    database = pymongo.MongoClient("192.168.50.2").linux_kernel
    return database

def c_link_h(c_object, h_includeName_filePath_map, h_file_map):
    '''一般是.h .c一一对应， 同名同层级的可以一对多'''
    ret = []
    c_name = re.sub(r'\.c$', '', c_object['c_name'])
    for local_h_path in c_object['local_include']:
        h_name = re.sub(r'\.h$', '', local_h_path.split("/")[-1])
        if c_name == h_name:
            # match 成功
            if local_h_path in h_file_map:
                ret.append(local_h_path)
    if ret:
        return ret
        
    for global_h_path in c_object['global_include']:
        h_name = re.sub(r'\.h$', '', global_h_path.split("/")[-1])
        if c_name == h_name:
            # match 成功
            if global_h_path in h_includeName_filePath_map:
                ret.extend(h_includeName_filePath_map[global_h_path])
    return ret


def pipe_handle(project_path, year, version):
    # 提取并且格式化后的 file object
    c_data_out = []
    h_data_out = []
    logging.info("start to extract file")
    
    with Pool(1) as p:
        c_data_out = p.starmap(extract_c_file, [(file_path,project_path) for file_path in find_c_files(project_path)], chunksize=1)
        logging.info("c file submit complete")
        h_data_out = p.starmap(extract_c_file, [(file_path,project_path) for file_path in find_h_files(project_path)], chunksize=1)
        logging.info("h file submit complete")
              
    logging.info("c file count: %d, h file count %d",len(c_data_out),len(h_data_out))
    
    # 建立 golbal_incude 的 maping
    global_include_name_mapping = collections.defaultdict(list)
    file_path_obj_mapping = dict()
    
    for obj in itertools.chain(c_data_out,h_data_out):
        # 所有 对象的文件路径映射
        file_path_obj_mapping[obj['file_path']] = obj
        # 全局路径中可能的名字，这部分会存在过多的引用
        for package_name in obj['my_include_name_list']:
            global_include_name_mapping[package_name].append(obj)

    # 将每个h的引入树形遍历，补全引入的tree，
    # 要有从 .h 找到 .c 的索引， 也要有 .c 找到 .h 的索引
    
    @functools.lru_cache(1_000_000)
    def deep_ref_scan(file_path):
        obj = file_path_obj_mapping[file_path]
        ref_out_obj_file_path = []
        func_name_list = set()
        
        for include_name in obj['local_include']:
            if ref_obj := file_path_obj_mapping.get(include_name):
                ref_out_obj_file_path.append(ref_obj['file_path'])
                
        for include_name in obj['global_include']:
            if ref_obj_list := global_include_name_mapping.get(include_name):
                ref_out_obj_file_path.extend([item['file_path'] for item in ref_obj_list])
                
        for func_data in obj['func_data']:
            if not func_data[4]:
                # 非 static
                func_name_list.add(func_data[0])
        
        return ref_out_obj_file_path, func_name_list
        
    project_h_ref_tree_mapping = collections.defaultdict(lambda: {})
    # 找到 obj 的所有 include 以及其定义的 func
    
    for obj in h_data_out:
        obj_path_name = obj['file_path']
        todo_pool = set([obj_path_name])
        complete_pool = set()
        while todo_pool:
            file_path = todo_pool.pop()
            ref_out_obj_file_path, func_name_list = deep_ref_scan(file_path)
            if func_name_list:
                project_h_ref_tree_mapping[obj_path_name][file_path] = func_name_list
            complete_pool.add(file_path)
            
            for task_path in project_h_ref_tree_mapping:
                if task_path not in complete_pool:
                    todo_pool.add(task_path)
    # complete project_h_ref_tree_mapping
    
    # clear lru cache
    deep_ref_scan.cache_clear()
    
    # 从 h 文件，找到 .c 文件中对应的方法
    c_func_ref_h_func_dict = collections.defaultdict(dict)
    func_link_h_to_c = collections.defaultdict(list)
    for obj in c_data_out:
        obj_path_name = obj['file_path']
        func_name_set = set()
        for item in obj['func_data']:
            # 非 static
            if not item[4]:
                func_name_set.add(item[0])
                
        if not func_name_set:
            # 没有可以被外部引用的 func, .c 文件
            continue
        
        # 遍历其 ref， 找到同名的 func
        # 合并 include 集合
        include_dict = dict()
        for include_name in obj['local_include']:
            if ref_obj := file_path_obj_mapping.get(include_name):
                h_path = ref_obj['file_path']
                if h_path in project_h_ref_tree_mapping:
                    include_dict.update(project_h_ref_tree_mapping[h_path])
                
        for include_name in obj['global_include']:
            if ref_obj_list := global_include_name_mapping.get(include_name):
                for ref_obj in ref_obj_list:
                    h_path = ref_obj['file_path']
                    if h_path in project_h_ref_tree_mapping:
                        include_dict.update(project_h_ref_tree_mapping[h_path])
     
        # 将 .h 文件的 func ref 到 .c 文件
        for h_path, func_set in include_dict.items():
            func_intersection = func_name_set & func_set
            # links  
            for func_name in func_intersection:
                func_link_h_to_c[(h_path,func_name)].append(obj_path_name)
                
    # 建立项目 ID
    GLOBAL_FUNC_ID = 0
    MASTER_FUNC_MAP = {}
    for item in c_data_out:
        file_path = item['file_path']

        for [func_name, lineCount, strCount, linksOut_list, func_static] in item['func_data']:
            key = (file_path, func_name)
            MASTER_FUNC_MAP[key] = {
                "_id": GLOBAL_FUNC_ID,
                "func_path": file_path,
                "static":func_static,
                "func_name": func_name,
                "line_count": lineCount,
                "str_count": strCount,
                "h_file_path_list": [],
                "linksIn_id_list": [],
                "linksOut_func_list": linksOut_list,
            }
            GLOBAL_FUNC_ID+=1
    logging.info('MASTER_FUNC_MAP length: %d', len(MASTER_FUNC_MAP))
    
    # 可以干活了， 将 .c 文件的 func 映射到 .h 文件
    for obj in c_data_out:
        # 先是判断内部 ref
        file_path = obj['file_path']
        self_func_name_set = set()
        for item in obj['func_data']:
            self_func_name_set.add(item[0])
        
        if not self_func_name_set:
            continue
            
        # 合并 include 集合
        include_dict = dict()
        for include_name in obj['local_include']:
            if ref_obj := file_path_obj_mapping.get(include_name):
                h_path = ref_obj['file_path']
                if h_path in project_h_ref_tree_mapping:
                    include_dict.update(project_h_ref_tree_mapping[h_path])
                
        for include_name in obj['global_include']:
            if ref_obj_list := global_include_name_mapping.get(include_name):
                for ref_obj in ref_obj_list:
                    h_path = ref_obj['file_path']
                    if h_path in project_h_ref_tree_mapping:
                        include_dict.update(project_h_ref_tree_mapping[h_path])
     
        # 反转 include_dict
        reverse_include_dict = collections.defaultdict(list)
        for h_path, func_name_list in include_dict.items():
            for func_name in func_name_list:
                reverse_include_dict[func_name].append(h_path)

        for item in obj['func_data']:
            func_name = item[0]
            source_func_key = (file_path, func_name)
            source_func_id = MASTER_FUNC_MAP.get(source_func_key,{})['_id']
            if not source_func_id:
                logging.warning("source_func_key miss:%s",source_func_key)
                continue
            
            for ref_func_name in item[3]:
                if ref_func_name in self_func_name_set:
                    # 内部 call
                    target_func_key = (file_path, ref_func_name)
                    MASTER_FUNC_MAP[target_func_key]['linksIn_id_list'].append(source_func_id)
                else:
                    # 外部 call
                    if h_path_list:= reverse_include_dict.get(ref_func_name):
                        for h_path in h_path_list:
                            key = (h_path, ref_func_name)
                            for c_obj_path in func_link_h_to_c.get(key,[]):
                                target_func_key = (c_obj_path,ref_func_name)
                                MASTER_FUNC_MAP[target_func_key]['linksIn_id_list'].append(source_func_id)
                                
    # import pdb
    # pdb.set_trace()

    database = get_mongo_database()
    collection = database[f'func_graph_{version}_{year}']
    collection.drop()
    collection.create_index([("func_path", pymongo.DESCENDING),("func_name", pymongo.DESCENDING),("h_file_path_list", pymongo.DESCENDING),("static", pymongo.DESCENDING)],
                            background=True)

    collection.create_index([("func_name", pymongo.DESCENDING),("h_file_path_list", pymongo.DESCENDING)],
                            background=True)
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
        
    logging.info("已完成：%d, 耗时：%d",i, int(time.time() - time_start))
    

def process_bulk_write(queue, key_id_map, year, version):
    database = get_mongo_database()
    p_collection = database[f'func_graph_{version}_{year}']
    while (job_item:= queue.get()) != "over":
        item, full_h_path_list = job_item
        file_path = item['file_path']
        mongodb_operate = []
        for [func_name, lineCount, strCount, linksOut_list, func_static] in item['func_data']:
            key = (file_path, func_name)
            linksin_id = key_id_map[key]
            for out_func_name in linksOut_list:
                # 如果自己 include 自己的 package ， 只保留一个就行了
                if func_name != out_func_name:
                    # for full_h_path in full_h_path_list:
                        # 对外部的 package 每个都遍历一遍
                    mongodb_operate.append(UpdateMany({'func_name':out_func_name ,'h_file_path_list':{'$in':full_h_path_list},'func_path':{'$ne':file_path}, 'static': False},{"$push":{'linksIn_id_list':linksin_id}}))
                # 自己就对自己加一次，自己内部的方法，不用再按package计数了， 当然我这里也没判断是不是内部的方法，让数据库自行判断了
                mongodb_operate.append(UpdateMany({'func_name':out_func_name ,'func_path':file_path,},{"$push":{'linksIn_id_list':linksin_id}}))
                    
        if mongodb_operate:
            p_collection.bulk_write(mongodb_operate)


def scan_commit(commit_version, repo):
    try:
        result = repo.git.checkout( commit_version, force=True)
        logging.info("checkout to version: %s", commit_version)
    except git.exc.GitCommandError as e:
        if "File name too long" in str(e):
            # 处理 File name too long 异常
            logging.warning(f"{self.full_name}: {commit_version.hexsha}, Caught File name too long error: {e}")
            return
        elif "Please commit your changes or stash them before you switch branches" in str(e):
            repo.git.checkout("-b", "tmp")
            repo.git.stash()
            result = repo.git.checkout(commit_version, force=True)
            logging.warning("Please commit your changes or stash them before you switch branches")
        else:
            logging.exception(e)
            logging.warning(f"{self.full_name}: {version} : {commit_version.hexsha}, un handle error")
            # 将其他异常继续向上抛出
            raise e
    # checkout 已经完成了， 现在需要 scan code


def git_histroy_review(project_source_path, version):
    
    repo = git.Repo(project_source_path)
    
    branch_list = []

    for branch in repo.remotes[0].fetch():
        branch_list.append([branch, len(list(repo.iter_commits(branch.name)))])
    master_branch = branch_list[0][0]
        
    year_dict = collections.defaultdict(list)

    for commit in repo.iter_commits(master_branch.name):
        committed_datetime = commit.committed_datetime
        year_str = committed_datetime.year
        year_dict[year_str].append(commit)

    year_commit_dict = {}
    for year_str, commit_list in year_dict.items():
        commit_list.sort(key=lambda x:x.committed_datetime,reverse=True)
        year_commit_dict[year_str]=commit_list[0]
        
        
    database = get_mongo_database()
    repo_stats_collection = database[f'repo_stats_{version}']
    
    for year_str, commit in year_commit_dict.items():
        # if year_str > 2020:
        #     continue
        logging.info("start: %s", year_str)
        scan_commit(commit, repo)

        # pipe_handle(project_source_path, year_str, version)
        # logging.info("scan complete: %s", year_str)
        
        total_files, total_size = count_files_and_size(project_source_path)
        repo_stats_collection.update_one({'_id':year_str},{'$set':{'count':total_files, 'size':total_size}},upsert=True)


def test_link_linux_kernel(project_source_path):
    
    pipe_handle(project_source_path, "test", "test")
    logging.info("scan complete: %s", year_str)
        

    
def linux_kernel_commit_history_load(project_source_path):
    
    repo = git.Repo(project_source_path)
    
    database = get_mongo_database()
    repo_commit_log_collection = database[f'repo_commit_log']
    
    for i, commit in enumerate(repo.iter_commits("master")):
        repo_commit_log_collection.update_one({'_id':str(commit)},{'$set':{
            'author_email':commit.author.email,
            'author_name':commit.author.name,
            'committed_datetime':commit.committed_datetime,
            'size':commit.size,
            'summary':commit.summary,
            'message':commit.message,
            'stats_files':commit.stats.files,
            'stats_total':commit.stats.total,
            }},upsert=True)
