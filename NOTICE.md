# 来源与许可

本仓库自编Python/Shell工具、中文说明和示意图采用MIT许可。没有重新发布原厂固件、厂商模块、设备分区、ADB密钥或个人录音。读者自己的运行时镜像与备份只保存在`work/`。

使用/参考的上游：

- [Magisk v30.7](https://github.com/topjohnwu/Magisk/releases/tag/v30.7)：镜像修补、magiskboot、magiskpolicy、BusyBox、原生root。由读者从官方Release下载，保持上游许可；不随本仓库分发二进制。固定APK SHA256：`e0d32d2123532860f97123d927b1bb86c4e08e6fd8a48bfc6b5bee0afae9ebd5`。
- [Magisk安装说明](https://topjohnwu.github.io/Magisk/install.html)：通用背景，不把通用流程当成本机已验证方案。
- [Android Platform-Tools](https://developer.android.com/tools/releases/platform-tools)：ADB/Fastboot。由操作系统包管理器或读者从官方获取，许可归上游。
- [PyUSB](https://github.com/pyusb/pyusb)：USB传输依赖。通过requirements安装，不内嵌上游源码。
- [MTKClient seccfg实现](https://github.com/bkerler/mtkclient/blob/main/mtkclient/Library/Hardware/seccfg.py)：辅助理解V4格式。成功路线没有使用下载代理刷写，仓库不内嵌MTKClient。
- [公开MTK HACC接口](https://android.googlesource.com/kernel/mediatek/+/android-mtk-3.18/drivers/misc/mediatek/masp/asfv2/mach/hacc_export.c)：辅助理解接口，随后与本机实际4.4内核核对。

USB CDC/READY路径、原厂bdft配置入口、AVB1元数据修正、当前内核ABI模块构建与HACC回验，均以本机观察、反汇编与实测为依据。其他工具的存在不代表本机支持它们的一键命令。
