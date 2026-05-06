---
name: commit
description: 提交代码
---
# commit

## 流程
1.查看工作区文件变动，更具修改内容生成一条简短的 subject 

2.commit message 必须使用 Conventional Commits 规范，格式如下
```shell
<type>: <subject>
```
type必须为一下内容：

* feat: 新功能 (Feature)
* fix: 修补 Bug
* docs: 仅修改了文档 (Documentation)
* style: 代码格式调整，不影响代码逻辑 (如空格、格式化、缺少分号等)
* refactor: 代码重构，即不是新增功能，也不是修改 Bug
* perf: 性能优化 (Performance)
* test: 添加或修改测试代码 (Test)
* chore: 构建过程或辅助工具的变动 (如更新依赖、修改 Webpack 配置)
* revert: 回退上一次或多次提交