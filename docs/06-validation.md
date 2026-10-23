# 6. 验证范围

## 原方法在一台真实设备上的证据

型号：小度智能屏1S XDH-29-B1，板型X7B_MAINBOARD_P3，MT8167，Android8.1/ARM32。

- Preloader READY→METAMETA，META命令行与uid0均确认；FACTFACT未取得可用授权，不计成功。
- 写入自己的ADB公钥后，正常系统认证ADB与无线ADB跨重启恢复。
- 原厂bdft维护入口的真实输出为uid0，普通ADB仍uid2000。
- 原生Magisk30.7开机、su、模块、systemless、实际zygote映射中的Zygisk验证通过。
- 独立Fastboot→维护Recovery的USB认证和root验证通过。
- HACC user1失败记录保留，user0四项加密/解密回验通过。
- seccfg仅写首512字节，全分区比较33字节变化；未修改LK/LK2或fuse。
- 原厂Fastboot `unlocked=yes / secure=no`，正常系统`flash.locked=0 / orange`，su继续uid0。

这些是原始分阶段实测结果，没有把未成功路线改成成功，没有声称跨机准确率或任意固件通用。

## 本公开重构版如何验证

公开版去除了私人路径、USB端口、固定IP/MAC、作者公钥和预先生成的镜像。发布前会做：

- Python编译与全部CLI帮助检查；
- 锁配置解析、候选变更范围、错版本/错长度/已解锁拒绝等离线单元测试；
- 使用原项目小型启动镜像在本机离线校验AVB1，重构boot构建输出也独立验证；
- HACC ARM代码生成/模块构建的离线检查；
- 用已有设备只读`doctor`检查连接与版本，不重复写设备分区；
- 发布包内容、中文文档链接、私人数据与打包清单检查。

**没有为了发布教程再对日用设备重新执行USB冷启动、刷boot/recovery、加载HACC模块或写seccfg。** 因此新封装命令的硬件写入分支不标成重新实机验收；底层方法的原始实测与公开封装的自测分开记录。最终具体检查结果写入`validation.json`。

## 反馈方式

Issue请提供：型号、完整固件版本、具体命令、去掉设备标识后的错误输出。不上传`work/`、ADB私钥、校准分区、自己的完整镜像、账号数据。不同内核版本的适配应独立核对机器码与ABI，不能只修改配置里的版本字符串。
