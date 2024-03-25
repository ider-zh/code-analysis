import subprocess, json


# ctage 获取文件定义的内容
def ctage(file_path):
    cmd = [
        "ctags",
        "--kinds-c=+p+x",
        "-x",
        "-u",
        # "--output-format=json",
        # "--excmd=number",
        # "--list-fields",
        # "--extras='-{anonymous}'",
        file_path,
    ]

    ctags_process = subprocess.Popen(cmd, stdout=subprocess.PIPE)

    # Create the second process: grep
    grep_cmd = ["grep", "-avE", "^operator |CONFIG_"]
    grep_process = subprocess.Popen(
        grep_cmd, stdin=ctags_process.stdout, stdout=subprocess.PIPE
    )

    # Close the stdout of the ctags process since it's no longer needed
    ctags_process.stdout.close()

    # Create the third process: awk
    awk_cmd = ["awk", '{print $1" "$2" "$3}']
    awk_process = subprocess.Popen(
        awk_cmd,
        stdin=grep_process.stdout,
        stdout=subprocess.PIPE,
        universal_newlines=True,
    )

    # Close the stdout of the grep process since it's no longer needed
    grep_process.stdout.close()

    # Get the output of the awk process
    output, _ = awk_process.communicate()

    data_list = []
    # print(p.stdout)
    ps = output.splitlines()
    for l in ps:
        ident, type, line = l.split(" ")
        line = int(line)

        data_list.append([ident, type, line])
    return data_list


if __name__ == "__main__":
    # file_path = "/mnt/wd01/github/linux_old1/arch/arm64/kernel/signal.c"
    file_path = "/mnt/wd01/github/linux_old1/arch/arm64/kernel/kexec_image.c"
    ret = ctage(file_path)
    for row in ret:
        print(row)
