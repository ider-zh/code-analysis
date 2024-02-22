const fs = require('fs');
const path = require('path');
const vsctm = require('vscode-textmate');
const oniguruma = require('vscode-oniguruma');

const wasmBin = fs.readFileSync(path.join(__dirname, './node_modules/vscode-oniguruma/release/onig.wasm')).buffer;
const vscodeOnigurumaLib = oniguruma.loadWASM(wasmBin).then(() => {
    return {
        createOnigScanner(patterns) { return new oniguruma.OnigScanner(patterns); },
        createOnigString(s) { return new oniguruma.OnigString(s); }
    };
});

const languageMap = {
    'source.js': 'tmLanguage/JavaScript.tmLanguage.json',
    'source.cpp': 'tmLanguage/cpp.tmLanguage.json',
    'source.c': 'tmLanguage/c.tmLanguage.json',
}
const registryMap = {}
for (let [scopeKey, tmLanguageFilePath] of Object.entries(languageMap)) {
    registryMap[scopeKey] = new vsctm.Registry({
        onigLib: vscodeOnigurumaLib,
        loadGrammar: () => {
            let grammarPath = path.resolve(__dirname, tmLanguageFilePath);;
            return Promise.resolve(vsctm.parseRawGrammar(fs.readFileSync(grammarPath).toString(), grammarPath));

        }
    });
}

function containsAll(originArray, includeArrays, excludeArrays=[]) {
    const allIncluded = includeArrays.every(value => originArray.includes(value));
    if (allIncluded == false)
        return false
    return excludeArrays.every(value => !originArray.includes(value));

}

const code_str_count = (code_list) => {
    let count = 0;
    code_list.forEach(text => {
        // 使用正则表达式去除所有空白字符
        const cleanedText = text.replace(/\s+/g, '');
        // 统计字符数量
        count += cleanedText.length;
    });
    return count;
};

function handleLineTokensCpp(lineTokens, line) {

    const retObj = {
        func_name: null,
        func_static: false,
        ref_func_name_list: [],
    }


    console.log(`\nTokenizing line: ${line}`);
    for (let j = 0; j < lineTokens.tokens.length; j++) {
        const token = lineTokens.tokens[j];
        console.log(` - token from ${token.startIndex} to ${token.endIndex} ` +
            `(${line.substring(token.startIndex, token.endIndex)}) ` +
            `with scopes ${token.scopes.join(', ')}`
        );

        if (containsAll(token.scopes, ["entity.name.function.definition.cpp"])) {
            const func_name = line.substring(token.startIndex, token.endIndex)
            retObj.func_name = func_name
        }
        if (containsAll(token.scopes, ["storage.modifier.static.cpp"])) {
            retObj.func_static = true
        }

        if (containsAll(token.scopes, ["entity.name.function.call.cpp"])) {
            const func_name = line.substring(token.startIndex, token.endIndex)
            retObj.ref_func_name_list.push(func_name)
        }

    }

}


function handleLineTokensC(lineTokens, line) {

    const retObj = {
        func_name: "",
        func_static: false,
        ref_func_name_list: [],
        bracket_begin_count: 0,
        bracket_end_count: 0,
        global_include: [],
        local_include: []
    }


    console.log(`\nTokenizing line: ${line}`);
    for (let j = 0; j < lineTokens.tokens.length; j++) {
        const token = lineTokens.tokens[j];
        console.log(` - token from ${token.startIndex} to ${token.endIndex} ` +
            `(${line.substring(token.startIndex, token.endIndex)}) ` +
            `with scopes ${token.scopes.join(', ')}`
        );

        if (containsAll(token.scopes, ["meta.function.c", "entity.name.function.c"])) {
            const func_name = line.substring(token.startIndex, token.endIndex)
            retObj.func_name = func_name
        }
        if (containsAll(token.scopes, ["storage.modifier.c"])) {
            retObj.func_static = true
        }
        if (containsAll(token.scopes, ["meta.function-call.c", "entity.name.function.c"])) {
            const func_name = line.substring(token.startIndex, token.endIndex)
            retObj.ref_func_name_list.push(func_name)
        }
        if (containsAll(token.scopes, ["punctuation.section.block.end.bracket.curly.c"])) {
            retObj.bracket_end_count += 1
        }
        if (containsAll(token.scopes, ["punctuation.section.block.begin.bracket.curly.c"])) {
            retObj.bracket_begin_count += 1
        }
        if (containsAll(token.scopes, ["string.quoted.other.lt-gt.include.c"],
    ["punctuation.definition.string.begin.c","punctuation.definition.string.end.c"])) {
            const func_name = line.substring(token.startIndex, token.endIndex)
            retObj.global_include.push(func_name)
        }
        if (containsAll(token.scopes, ["string.quoted.double.include.c"],
        ["punctuation.definition.string.begin.c","punctuation.definition.string.end.c"])) {
            const func_name = line.substring(token.startIndex, token.endIndex)
            retObj.local_include.push(func_name)
        }

    }
    return retObj
}



function GetTextMateService(scope,textData, callback) {

    // 对 textData，进行预处理
    // Replace single-line comments starting with //
    const singleLineCommentsRemoved = textData.replace(/\/\/(.*$)/gm, '');

    // Replace multi-line comments /* ... */
    const multiLineCommentsRemoved = singleLineCommentsRemoved.replace(/\/\*[\s\S]*?\*\//g, '');

    // Replace consecutive empty lines with a single empty line
    const emptyLinesRemoved = multiLineCommentsRemoved.replace(/^[\t ]*\n/gm, '');

    // console.log(emptyLinesRemoved)

    const registry = registryMap[scope]
    if (!registry) {
        callback(null, { text: JSON.stringify({ text: "fail" }) });
    }

    const func_data = []
    const global_include = []
    const local_include = []
    // Load the JavaScript grammar and any other grammars included by it async.
    registry.loadGrammar(scope).then(grammar => {

        const text = emptyLinesRemoved.split(/\r\n|\r|\n/);
        let ruleStack = vsctm.INITIAL;

        let func_name = ""
        let func_static = false
        let func_start_line = -1
        let func_code_list = []
        let ref_func_name_list = []
        let brace_count = 0
        let brace_flag = false

        for (let i = 0; i < text.length; i++) {
            const line = text[i];
            const lineTokens = grammar.tokenizeLine(line, ruleStack);
            let lineStats = null
            switch (scope) {
                case "source.cpp":
                    lineStats = handleLineTokensCpp(lineTokens, line)
                    break
                case "source.c":
                    lineStats = handleLineTokensC(lineTokens, line)
                    break
            }

            // 第一次匹配到函数名
            if (func_name === "") {
                if (lineStats.func_name !== "") {
                    func_name = lineStats.func_name
                    func_static = lineStats.func_static
                    func_start_line = i
                    func_code_list = []
                    ref_func_name_list = []
                    brace_count = 0
                    brace_flag = false
                }
            }
            ref_func_name_list.push(...lineStats.ref_func_name_list)
            global_include.push(...lineStats.global_include)
            local_include.push(...lineStats.local_include)
            func_code_list.push(line)

            if (lineStats.bracket_begin_count > 0 ||
                lineStats.bracket_end_count > 0
            ) {
                brace_count += (lineStats.bracket_begin_count - lineStats.bracket_end_count)
                brace_flag = true
            }
            if (brace_count === 0 && brace_flag === true && func_name !== "") {
                func_line_count = i - func_start_line + 1
                func_data.push([func_name,
                    func_line_count,
                    code_str_count(func_code_list),
                    ref_func_name_list,
                    func_static])
                func_name = ""
                func_static = false
            }

            ruleStack = lineTokens.ruleStack;
        }
        if (func_name !== "") {
            func_line_count = text.length - func_start_line + 1
            func_data.push([func_name,
                func_line_count,
                code_str_count(func_code_list),
                ref_func_name_list,
                func_static])
        }
        callback(null, { text: JSON.stringify({
            func_data,
            global_include,
            local_include
        }) });
    });
}

// const PROTO_PATH = fs.readFileSync(path.resolve(__dirname, './../protos/text_mate.proto'), 'utf8')
const test_code = path.resolve(__dirname, './test_code.txt')

const data = fs.readFileSync(test_code, { encoding: 'utf8' });


GetTextMateService('source.c',data, (_,ret)=>{console.log(ret)})