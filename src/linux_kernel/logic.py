# 继续拆解加速
import time
import pymongo
from pymongo import UpdateMany
from multiprocessing import Process, Queue
import collections
import re
from multiprocessing import Pool
import git
import logging.config
logging.config.fileConfig('config/logging.conf')

from src.linux_kernel.utils import (
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
    
    # for file_path in find_c_files(project_path):
    #     data = extract_c_file(file_path, project_path)
    #     c_data_out.append(data)
    
    # for file_path in find_h_files(project_path):
    #     data = extract_c_file(file_path, project_path)
    #     h_data_out.append(data)
    
    with Pool(40) as p:
        c_data_out = p.starmap(extract_c_file, [(file_path,project_path) for file_path in find_c_files(project_path)], chunksize=1)
        logging.info("c file submit complete")
        h_data_out = p.starmap(extract_c_file, [(file_path,project_path) for file_path in find_h_files(project_path)], chunksize=1)
        logging.info("h file submit complete")
        
    # with concurrent.futures.ProcessPoolExecutor(max_workers=40) as executor:
    #     # Start the load operations and mark each future with its URL
    #     ret_list = [executor.submit(extract_c_file, file_path, project_path) for file_path in find_c_files(project_path)]
    #     logging.info("c file submit complete")
    #     for future in concurrent.futures.as_completed(ret_list):
    #         data = future.result()
    #         c_data_out.append(data)
            
    #     ret_list = [executor.submit(extract_c_file, file_path, project_path) for file_path in find_h_files(project_path)]
    #     logging.info("h file submit complete")
    #     for future in concurrent.futures.as_completed(ret_list):
    #         data = future.result()
    #         h_data_out.append(data)
            
    logging.info("c file count: %d, h file count %d",len(c_data_out),len(h_data_out))
    
    # 构建 .h 的 map， 短h map 长h
    h_includeName_filePath_map = collections.defaultdict(list)
    # 长h map h_object
    h_file_map = {}
    for item in h_data_out:
        for key in item['my_include_name_list']:
            h_includeName_filePath_map[key].append(item['file_path'])
        h_file_map[item['file_path']] = item
    logging.info('h_includeName_filePath_map length: %d,  lh_file_map length: %d', len(h_includeName_filePath_map),len(h_file_map))

    h_includeName_c_object_map = collections.defaultdict(list)
    for item in c_data_out:
        local_h_path_list = c_link_h(item, h_includeName_filePath_map, h_file_map)
        for local_h_path in local_h_path_list:
            h_includeName_c_object_map[local_h_path].append(item)
    logging.info('h_includeName_c_object_map length: %d', len(h_includeName_c_object_map))
    
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

    for local_h_path, c_object_list in h_includeName_c_object_map.items():

        for item in c_object_list:
            file_path = item['file_path']
            for [func_name, lineCount, strCount, linksOut_list, func_static] in item['func_data']:
                key = (file_path, func_name)
                if key in MASTER_FUNC_MAP:
                    MASTER_FUNC_MAP[key]['h_file_path_list'].append(local_h_path)
                else:
                    logging.info('miss key: %s', key)
                    logging.info('local_h_path: %s', local_h_path)

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
        
    # 开始分析引用
    key_id_map = {}
    for key,item in MASTER_FUNC_MAP.items():
        key_id_map[key] = item['_id']

    queue = Queue(1000)
    ps_count = 40
    ps = []
    for _ in range(ps_count):
        p = Process(target=process_bulk_write,args=(queue, key_id_map, year, version))
        p.start()
        ps.append(p)

    time_start = time.time()
    for i, item in enumerate(c_data_out):
        if i% 10000 == 0:
            logging.info("已完成：%d, 耗时：%d",i, int(time.time() - time_start))

        file_path = item['file_path']
        full_h_path_list = item['local_include']
        for global_include_items in item['global_include']:
            full_h_path_list.extend(h_includeName_filePath_map.get(global_include_items, []))

        job_item = (item, full_h_path_list)
        queue.put(job_item)

    for _ in range(ps_count):
        queue.put("over")
    for p in ps:
        p.join()
        
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
