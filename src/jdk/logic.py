import subprocess
import pathlib
import zipfile
import shutil
from multiprocessing import Pool
import uuid
import pymongo
import math
import logging.config

logging.config.fileConfig("config/logging.conf")

temp_path = "/dev/shm/"

descriptor_flag = "  descriptor: "
code_flag = "    Code:"
line_number_flag = "    LineNumberTable:"
local_variable_flag = "    LocalVariableTable:"
# new
# checkcast
# ldc
# ldc_w
# anewarray
# putstatic
# lookupswitch
# instanceof
# getfield
# putfield
# ldc2_w
# multianewarray
# tableswitch
# invokestatic 调用静态方法，这种调用也是静态绑定的，因此执行速度较快。
# invokevirtual 调用所有的虚方法，这种调用是动态绑定的。
# invokedynamic 支持动态语言的方法调用
# invokeinterface 调用接口方法
# invokespecial 指令用于调用实例构造器
# getstatic 调用变量

code_step_set = set(
    [
        "new",
        "getfield",
        "multianewarray",
        "tableswitch",
        "ldc2_w",
        "getstatic",
        "putfield",
        "anewarray",
        "lookupswitch",
        "instanceof",
        "putstatic",
        "ldc_w",
        "ldc",
        "checkcast",
        "invokestatic",
        "invokevirtual",
        "invokedynamic",
        "invokeinterface",
        "invokespecial",
    ]
)
code_step_method_set = set(
    [
        "invokestatic",
        "invokevirtual",
        "invokedynamic",
        "invokeinterface",
        "invokespecial",
    ]
)

jdk_versions = {
    7: "java-se-7u75-ri",
    11: "jdk-11.0.2",
    14: "jdk-14.0.2",
    17: "jdk-17.0.2",
    20: "jdk-20.0.2",
    23: "jdk-23",
    8: "java-se-8u43-ri",
    12: "jdk-12.0.2",
    15: "jdk-15.0.2",
    18: "jdk-18.0.2",
    21: "jdk-21.0.2",
    9: "jdk-9.0.4",
    10: "jdk-10.0.2",
    13: "jdk-13.0.2",
    16: "jdk-16.0.2",
    19: "jdk-19.0.1",
    22: "jdk-22",
}


def count_leading_spaces(string):
    """
    Counts the number of leading spaces in a given string.

    Args:
        string (str): The input string.

    Returns:
        int: The number of leading spaces in the input string.
    """
    count = 0
    for char in string:
        if char == " ":
            count += 1
        else:
            break
    return count


def init_class_obj(file_path):
    return {
        "file": file_path,
        "type": "",  #  class interface
        "flag": "",  # private, protected and public
        "name": "",
        "extends": None,
        "implements": [],
        "fields": [],
        "methods": [],
    }


def init_method_obj():
    return {
        "flag": "",  # private, protected and public
        "name": "",
        "descriptor": "",
        "code_length": 0,
        "line_start": 0,
        "line_end": 0,
        "methods": [],
    }


def extract_class_init_row(row):
    class_flag = "class "
    interface_flag = "interface "
    implements = []
    flag = None
    extends = []
    class_type = ""
    if class_flag in row:
        class_type = "class"
        flag = class_flag
    elif interface_flag in row:
        class_type = "interface"
        flag = interface_flag
    if flag:
        class_split = row.split(flag)
        text = class_split[-1].replace(" {", "").strip()

        implement_flag = " implements "
        extends_flag = " extends "
        if implement_flag in text:
            tmp_list = text.split(implement_flag)
            text = tmp_list[0]
            implements = [item.strip() for item in tmp_list[1].split(",")]
        if extends_flag in text:
            tmp_list = text.split(extends_flag)
            text = tmp_list[0]
            extends = [item.strip() for item in tmp_list[1].split(",")]
        class_name = text
        class_flag = ""
        if "public" in class_split[0]:
            class_flag = "public"
        elif "private" in class_split[0]:
            class_flag = "private"
        elif "protected" in class_split[0]:
            class_flag = "protected"
        return class_flag, class_name, extends, implements, class_type

    return "", "", extends, implements, class_type


def extract_method_init_row(row):
    row_split = row.strip().split(" ")
    if "(" not in row:
        method_name = row_split[-1]
    else:
        method_name = row.split("(")[0].split(" ")[-1]
    method_flag = ""
    if "public" in row_split[0]:
        method_flag = "public"
    elif "private" in row_split[0]:
        method_flag = "private"
    elif "protected" in row_split[0]:
        method_flag = "protected"
    return method_flag, method_name


def format_javap_output(javap_output: str, file_path: str):

    class_reslut_list = []
    class_obj = init_class_obj(file_path)
    method_obj = init_method_obj()
    state_flag = {"method_type": "", "lv3": ""}

    for row in javap_output.splitlines():

        space_count = count_leading_spaces(row)
        if space_count < 6:
            state_flag["lv3"] = ""

        # class start
        if space_count == 0 and class_obj["name"] == "":
            (
                class_obj["flag"],
                class_obj["name"],
                class_obj["extends"],
                class_obj["implements"],
                class_obj["type"],
            ) = extract_class_init_row(row)
            continue

        # class end
        if row == "}":
            if method_obj["name"] != "":
                class_obj["methods"].append(method_obj)
            class_reslut_list.append(class_obj)
            class_obj = init_class_obj(file_path)
            continue

        if space_count == 2:
            if method_obj["name"] != "":
                if state_flag["method_type"] == "method":
                    class_obj["methods"].append(method_obj)
                else:
                    class_obj["fields"].append(method_obj)
                method_obj = init_method_obj()
            method_obj["flag"], method_obj["name"] = extract_method_init_row(row)
            continue

        if space_count == 4:
            if code_flag == row:
                state_flag["lv3"] = "code"
            elif line_number_flag == row:
                state_flag["lv3"] = "line"
            elif local_variable_flag == row:
                state_flag["lv3"] = "local"
            elif descriptor_flag in row:
                method_obj["descriptor"] = (
                    row.replace(descriptor_flag, "").strip().replace("/", ".")
                )
                if "(" in method_obj["descriptor"]:
                    state_flag["method_type"] = "method"
                else:
                    state_flag["method_type"] = "field"
                continue

        if space_count >= 6:
            # print(state_flag['lv3'])
            if state_flag["lv3"] == "local":
                continue
            elif state_flag["lv3"] == "line":
                line_number = int(row.replace("line", "").strip().split(": ")[0])
                if method_obj["line_start"] == 0:
                    method_obj["line_start"] = line_number
                method_obj["line_end"] = line_number
                continue
            elif state_flag["lv3"] == "code":
                method_obj["code_length"] += 1

                code_split = row.strip().split("//")
                if len(code_split) == 1:
                    continue
                code_step = code_split[0].strip().split(" ")[1].strip()
                if code_step not in code_step_set:
                    logging.info("extecp code step: %s", row)

                # except invokedynamic
                #   17: invokedynamic #124,  0            // InvokeDynamic #5:accept:(Ljdk/internal/jshell/tool/Feedback$Setter;)Ljava/util/function/Consumer;
                #   22: invokeinterface #127,  2          // InterfaceMethod java/util/Collection.forEach:(Ljava/util/function/Consumer;)V
                if code_step in code_step_method_set:

                    method_split = code_split[1].strip().split(" ")
                    text_split = method_split[1].split(".")

                    if len(text_split) == 1:
                        class_path = ""
                        method_text_split = text_split[0].split(":")
                    else:
                        class_path = text_split[0].replace("/", ".")
                        method_text_split = text_split[1].split(":")
                    descriptor = method_text_split.pop().replace("/", ".")
                    method_name = ":".join(method_text_split).strip()
                    method_obj["methods"].append(
                        {
                            "class": class_path,
                            "method": method_name,
                            "descriptor": descriptor,
                        }
                    )

                    # 记录 method 调用

    return class_reslut_list


def run_javap(file_path):
    # 执行 javap 命令并获取输出

    javap_command = f"javap -s -c -p -l {file_path}"
    process = subprocess.Popen(
        javap_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True
    )

    # 获取命令的输出
    output, error = process.communicate()

    # 输出结果
    if output:
        ret = format_javap_output(output.decode("utf-8"), file_path)
        if len(ret) == 0:
            logging.info("empty format javap:%s", file_path)
        return ret
        # print("输出：")
        # import json
        # print(json.dumps(ret,indent=4))
    if error:
        logging.info("错误：%s", error.decode("utf-8"))
        return []


def test():
    # 示例调用
    file_path = "/tmp/ArraysParallelSortHelpers.class"
    file_path = "/tmp/Arrays.class"
    file_path = "/tmp/ArraysParallelSortHelpers$FJObject$Merger.class"
    file_path = "/tmp/ArrayPrefixHelpers\$DoubleCumulateTask.class"
    # file_path = "/tmp/ArrayList.class"
    file_path = "/dev/shm/579d01ef_90c5_48dd_9c69_4a488d7cac70/sun/net/www/protocol/jar/URLJarFileCallBack.class"
    file_path = "/tmp/GapContent\$InsertUndo.class"
    file_path = "/dev/shm/cbed0834_640e_431d_a65d_6f67db8fca23/sun/swing/FilePane$FileRenderer.class"
    file_path = "/tmp/Feedback\$Setter.class"
    # javap_command = "javap -p /tmp/Arrays.class"
    run_javap(file_path)


def handle_jdk78(jdk_path):
    jre_path = pathlib.Path(jdk_path).joinpath("jre/lib/rt.jar")
    dest_path = pathlib.Path(temp_path).joinpath(generate_uuid_as_directory_name())

    ret_list = []
    try:
        # 使用 zipfile 模块解压 jmod 文件
        with zipfile.ZipFile(jre_path, "r") as zip_ref:
            zip_ref.extractall(dest_path)

        # for file in dest_path.glob('**/*.class'):
        #     # print(file)
        #     ret = run_javap(file)
        #     ret_list.extend(ret)

        with Pool(20) as p:
            ret_list = p.starmap(
                run_javap,
                [(file_path.as_uri(),) for file_path in dest_path.glob("**/*.class")],
                chunksize=1,
            )

        return ret_list
        # yield file
    except Exception as e:
        logging.exception(e)
    finally:
        # shutil.rmtree(dest_path)
        pass


def handle_jdk8upper(jdk_path):
    jmobs_path = pathlib.Path(jdk_path).joinpath("jmods")

    logging.info(jmobs_path)
    ret_list = []
    for jmob_file in jmobs_path.glob("*.jmod"):
        dest_path = pathlib.Path(temp_path).joinpath(generate_uuid_as_directory_name())
        try:
            # 使用 zipfile 模块解压 jmod 文件
            with zipfile.ZipFile(jmob_file, "r") as zip_ref:
                zip_ref.extractall(dest_path)

            # for file in dest_path.glob('**/*.class'):
            #     # print(file)
            #     ret = run_javap(file)
            #     ret_list.extend(ret)

            with Pool(30) as p:
                ret = p.starmap(
                    run_javap,
                    [
                        (file_path.as_uri(),)
                        for file_path in dest_path.glob("**/*.class")
                    ],
                    chunksize=1,
                )
                ret_list.extend(ret)

                # yield file
        except Exception as e:
            logging.exception(e)
        finally:
            shutil.rmtree(dest_path)
            pass
    return ret_list


def generate_uuid_as_directory_name():
    # 生成 UUID
    uuid_str = str(uuid.uuid4())

    # 处理 UUID 字符串，使其适合作为目录名
    directory_name = uuid_str.replace("-", "_")  # 将 "-" 替换为 "_"

    return directory_name


def data_formate(extract_result):
    CLASS_DATA_DICT = {}
    METHOD_DATA_DICT = {}
    Method_ID = 0
    for item_list in extract_result:
        for item in item_list:
            if class_name := item.get("name"):
                if "<" in class_name:
                    class_name = class_name.split("<")[0]
                CLASS_DATA_DICT[class_name] = {
                    "file": item.get("file"),
                    "type": item.get("type"),
                    "flag": item.get("flag"),
                    "name": class_name,
                    "extends": item.get("extends"),
                    "implements": item.get("implements"),
                }

                for method_item in item.get("methods"):
                    Method_ID += 1

                    # todo， 将构造函数统一名字
                    method_name = method_item.get("name")
                    if method_name == class_name:
                        method_name = '"<init>"'
                    key = (class_name, method_name, method_item.get("descriptor"))
                    method_obj = {
                        "_id": Method_ID,
                        "class": class_name,
                        "flag": method_item.get("flag"),
                        "name": method_name,
                        "descriptor": method_item.get("descriptor"),
                        "code_length": method_item.get("code_length"),
                        "line_start": method_item.get("line_start"),
                        "line_end": method_item.get("line_end"),
                        "methods": method_item.get("methods"),
                        "methods_links": [],
                        "methods_links_miss": [],
                    }
                    METHOD_DATA_DICT[key] = method_obj

    METHOD_DATA_DICT_EXCEPT_descriptor = {}
    for key, v in METHOD_DATA_DICT.items():
        METHOD_DATA_DICT_EXCEPT_descriptor[(key[0], key[1])] = v

    return CLASS_DATA_DICT, METHOD_DATA_DICT, METHOD_DATA_DICT_EXCEPT_descriptor


def get_parent_method_key(class_data_dict, method_key):
    fa_keys = []
    child_class_name = method_key[0]
    if class_obj := class_data_dict.get(child_class_name):
        for fa_class_obj in class_obj.get("extends"):
            if fa_class_obj:
                # to check
                if "<" in fa_class_obj:
                    fa_class_obj = fa_class_obj.split("<")[0]
                fa_keys.append((fa_class_obj, method_key[1], method_key[2]))
    return fa_keys


def get_parent_method_key_2(class_data_dict, method_key):
    fa_keys = []
    child_class_name = method_key[0]
    if class_obj := class_data_dict.get(child_class_name):
        for fa_class_obj in class_obj.get("extends"):
            if fa_class_obj:
                # to check
                if "<" in fa_class_obj:
                    fa_class_obj = fa_class_obj.split("<")[0]
                fa_keys.append((fa_class_obj, method_key[1]))
    return fa_keys


def update_jdk_data(data_dict, version, database):
    collection = database[f"jdk_{version}"]
    batch_size = 10000
    result_data_pool = list(data_dict.values())

    num_batches = math.ceil(len(result_data_pool) / batch_size)

    # 对更新操作列表进行分批
    for batch_num in range(num_batches):
        start_idx = batch_num * batch_size
        end_idx = min((batch_num + 1) * batch_size, len(result_data_pool))

        collection.insert_many(result_data_pool[start_idx:end_idx])


def handle_jdk_version(version, database):
    miss_key_set = set()
    correct_key_set = set()
    expect_key_set = set()

    jdk_path = f"/home/ider/data/jdk_collect/{jdk_versions[version]}"
    if version <= 8:
        result_data = handle_jdk78(jdk_path)
    else:
        result_data = handle_jdk8upper(jdk_path)
    logging.info(len(result_data))

    CLASS_DATA_DICT, METHOD_DATA_DICT, METHOD_DATA_DICT_EXCEPT_descriptor = (
        data_formate(result_data)
    )
    logging.info(len(CLASS_DATA_DICT), len(METHOD_DATA_DICT))

    for method_key, method_obj in METHOD_DATA_DICT.items():
        for out_method in method_obj.get("methods"):

            out_class_name = (
                out_method["class"] if out_method["class"] else method_obj["class"]
            )
            # out_method_name = out_method["method"] if out_method["method"] != '"<init>"' else out_class_name
            out_method_name = out_method["method"]

            out_key = (out_class_name, out_method_name, out_method["descriptor"])
            # if out_key == ('hide', 'hide', '()V'):
            #     print(method_key, out_method)

            link_flag = False
            out_key_origin = out_key
            out_key_todo_set = set(
                [
                    out_key,
                ]
            )
            out_key_finsh_set = set()
            while out_key_todo_set:
                out_key = out_key_todo_set.pop()
                out_key_finsh_set.add(out_key)
                if out_obj := METHOD_DATA_DICT.get(out_key):
                    out_id = out_obj["_id"]
                    method_obj["methods_links"].append(out_id)
                    correct_key_set.add(out_key_origin)
                    link_flag = True
                    break
                else:
                    # todo: 增加一步，从父类中找方法
                    out_key_list_parent = get_parent_method_key(
                        CLASS_DATA_DICT, out_key
                    )
                    out_key_todo_set.update(
                        set(out_key_list_parent) - out_key_finsh_set
                    )
                    if out_key_todo_set:
                        continue
            #                 if out_key_origin == ('jdk.internal.net.http.Http1Exchange',
            #   '#25:makeConcatWithConstants',
            #   '(Ljava.lang.String;Ljava.lang.String;)Ljava.lang.String;'):
            #                     print(out_method,method_key)

            # 完全没有匹配上，这里就需要处理对象扩大化的匹配
            # 完全匹配的没有成功
            if not link_flag:

                if (
                    out_key_origin[1] in ["clone", '"<init>"']
                    or ":" in out_key_origin[1]
                ):
                    expect_key_set.add(out_key_origin)
                    method_obj["methods_links_miss"].append(out_method)
                    continue

                out_key_origin_2 = (out_key_origin[0], out_key_origin[1])
                out_key_todo_2_set = set(
                    [
                        out_key_origin_2,
                    ]
                )
                out_key_finsh_2_set = set()
                while out_key_todo_2_set:
                    out_key = out_key_todo_2_set.pop()
                    out_key_finsh_2_set.add(out_key)
                    if out_obj := METHOD_DATA_DICT_EXCEPT_descriptor.get(out_key):
                        out_id = out_obj["_id"]
                        method_obj["methods_links"].append(out_id)
                        correct_key_set.add(out_key_origin)
                        link_flag = True
                        break
                    else:
                        # todo: 增加一步，从父类中找方法
                        out_key_list_parent = get_parent_method_key_2(
                            CLASS_DATA_DICT, out_key
                        )
                        out_key_todo_2_set.update(
                            set(out_key_list_parent) - out_key_finsh_2_set
                        )
                        if out_key_todo_set:
                            continue

            if not link_flag:
                miss_key_set.add(out_key_origin)
                method_obj["methods_links_miss"].append(out_method)
                # print(out_key_origin)
                break
    logging.info("%s,%s", len(miss_key_set), len(correct_key_set))

    update_jdk_data(METHOD_DATA_DICT, version, database)


def main():

    database = pymongo.MongoClient("192.168.1.222").jdk
    for version in range(7, 22):
        handle_jdk_version(version, database)
