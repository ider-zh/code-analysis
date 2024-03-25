const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const tmpDir = "/dev/shm/"

async function writeCTextToTempFile(text) {
    const filename = `${crypto.randomBytes(8).toString('hex')}_${text.length}.c`;
    const filePath = path.join(tmpDir, filename);
  
    await fs.promises.writeFile(filePath, text);
  
    return filePath;
}

// 通过行号定位函数的开始， 通过函数名，限定函数的结束位置
// 一个文件中可能定义多个同名函数， 我们只取最后一个函数
function filtrCTagsMap(CTagsOutList){
    const lineFuncMap = new Map()
    let funcName = ""
    let startLineNumber = -1
    let funcType = ""
    for(let i in CTagsOutList){
        const element = CTagsOutList[i]
        const [ident, type, line ] = element
        const lineNumber = Number(line)    

        if (funcName !==""){
            lineFuncMap.set(startLineNumber, {funcName:ident, endLine: lineNumber-1, type:funcType})
            funcName = ""
            startLineNumber = -1
        }
        if (type === "function" || type === "marco"){
            funcName = ident
            startLineNumber = lineNumber
            funcType = "function"
        }
    };
    if (funcName !==""){
        lineFuncMap.set(startLineNumber, {funcName:funcName, endLine: 999999, type:funcType})
    }
    return lineFuncMap
}

async function getCTagsHandle(text) {
    const filePath = await writeCTextToTempFile(text)
    try {
      // 执行 ctags 命令
      const ctags = spawnSync('ctags', ['-x', '-u', '--kinds-c=+p+x',  filePath], { stdio: ['pipe', 'pipe', 'inherit'] });
  
      if (ctags.error) {
        throw ctags.error;
      }
  
      // 执行 grep 命令
      const grep = spawnSync('grep', ['-avE', '^operator |CONFIG_'], { input: ctags.stdout, stdio: ['pipe', 'pipe', 'inherit'] });
  
      if (grep.error) {
        throw grep.error;
      }
  
      // 执行 awk 命令
      const awk = spawnSync('awk', ['{print $1" "$2" "$3}'], { input: grep.stdout, encoding: 'utf8' });
  
      if (awk.error) {
        throw awk.error;
      }
  

       const cTagsOut = awk.stdout.trim().split("\n").map(row=>{
        return row.split(' ')
      })

      return filtrCTagsMap(cTagsOut)
  
    } catch (err) {
        console.error('Error:', err);
        return new Map();
    } finally{
        await fs.promises.unlink(filePath);
        // fs.promises.unlink(filePath);
    }
}

module.exports = {
    getCTagsHandle
  };