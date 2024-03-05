# code analysis
分析 jdk 内置 class 的代码长度和 import 次数
class 代码长度去掉了空行和注释
import * ，则该 package 下的 class 都+1


# develop

## npm 修改 mirror
https://juejin.cn/post/7238233943609966652


## release
1. fix js 过滤单行注释的方法， 原来的方法无法 cover awk 的语法， 这次用 gemini 提供的方法interp