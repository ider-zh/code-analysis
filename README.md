# code analysis
分析 jdk 内置 class 的代码长度和 import 次数
class 代码长度去掉了空行和注释
import * ，则该 package 下的 class 都+1


# develop

## npm 修改 mirror
https://juejin.cn/post/7238233943609966652


## release
1. fix js 过滤单行注释的方法， 原来的方法无法 cover awk 的语法， 这次用 gemini 提供的方法interp



# run
1. `make js_server` 启动 js 中的语言函数切分服务。
2. `make kernel-extract` 从代码仓库中提取代码中的文件及其函数， 依赖 1 服务。
3. `make main-cache` 将 2 处理好的文件，分析依赖，存储到数据库。