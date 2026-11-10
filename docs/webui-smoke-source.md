# WebUI Smoke 源码说明

## 参数要求

候选脚本 `scripts/smoke-webui.ps1` 需要**两个必填、非空参数**：

- `-Project`：调用者显式提供的目标项目根（原默认值 `.research-question` 已移除，不再自动取默认项目）。
- `-LogDirectory`：调用者显式提供的日志目录。脚本在该目录下用本轮 GUID 生成唯一的 stdout/stderr 文件名，不再使用固定 `$env:TEMP` 路径。

脚本不新增业务审核门槛，不自动查找真实项目。

## 执行影响

实际运行该脚本将：

1. **启动子进程**：`Start-Process python -m question_research_poc.cli run-web`，以 `WindowStyle Hidden` 后台启动 WebUI。
2. **发送本地 HTTP 请求**：向 `runtime.json` 中配置的 host:port（默认 127.0.0.1:8920，当前公开配置为 127.0.0.1:8775）发送最多 4 个 `Invoke-WebRequest`（首页 + 3 个 API），外加 20 次就绪轮询探测。
3. **可能写项目数据**：API 请求以 `-Project` 参数为 `root` 查询，实际运行可能触发服务端对项目目录的读写。

> 实际运行需用户**另行明确授权**。本次做源码适配、文本/差异核对及当前PowerShell7.5.2非执行解析（0错误）。只执行抽取的finally块并以抛错的假Stop-Process作受控检查；整个脚本、实际进程清理、服务及HTTP均未运行。

## 公开配置的定位

`config/runtime.json` 是一份**固定公开提交的配置源**，仅反映开发时的参数背景（host/port/default_root）。它不代表服务可启动、端口可用、或已经过测试。不要访问其端口。

## 日志唯一性 ≠ 权限/保密/成功

- GUID 生成的每轮日志文件名旨在减少名称碰撞，**不构成**文件权限正确、内容保密、或进程成功退出的证据。
- 日志目录由调用者提供，脚本在执行时创建（如不存在）；本轮未创建或读取任何日志目标。

## Contains 检查的性质

结果中的 `project_api_ok` / `completeness_api_ok` / `manifest_api_ok` 使用 `.Contains()` 做**字符串存在性**判断，仅检查响应体中是否包含特定子串，**不验证**响应内容的正确性、完整性或 schema 一致性。不可将 Contains 命名升级表述为内容正确性。

## Stop-Process 不构成经验证的清理

`finally` 块中的 `Stop-Process -Id $Process.Id` 使用本轮Start-Process返回对象记录的PID请求强制终止，保留 `WindowStyle Hidden`，不杀端口上的其他进程。该操作**不构成**经验证的环境清理或资源回收证据——进程是否真正退出、端口是否释放、子资源是否回收，均未经验证。


## 环境恢复的局部修补与实际检查

进程清理与环境恢复现以嵌套try/finally分开：即使清理过程抛出终止异常，也会进入原有PYTHONPATH恢复分支，随后原异常仍可传播。这保证恢复分支被尝试，不保证恢复操作本身失败时仍能成功。Owner仅抽取清理块，在原变量有非空值/原变量缺失两种受控状态下，让假Stop-Process抛错；原候选两个反例均未恢复，修补后两个控制均恢复，且异常未吞掉。真实Stop-Process调用0次，整个脚本/Start-Process/服务/HTTP均0次。该结果不覆盖真实进程、日志权限、空字符串、PowerShell5.1或完整服务生命周期。源码其它部分沿用既有候选。
