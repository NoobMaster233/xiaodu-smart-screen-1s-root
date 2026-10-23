# 3. 独立救援与原生 Magisk

已经有维护 root 不代表随便修补 boot 都能启动。本机还要解决 AVB1 签名、Recovery root 和原厂自动恢复 Recovery。按先救援、后 boot 的顺序完成。

## 3.1 范围与本机材料

完整 BL/原生 boot 路线实测基于 `DuerShow_MT8167s_v1.68.2.20250324172557685.R`。`build-boot` 只接受核对过哈希的官方该版本 boot；其他版本会停止。

本机最初是 1.69.3，期间曾用官方 1.68.1 完整包与 1.68.2 差分恢复系统。这是另一次完整系统维护，不能误写为“整个项目从未刷过系统”。公开工具**不自动降级或刷整包**。若版本不符，可先停在上一章的维护 root；不要为了跑脚本盲目跨版本刷机。

在当前合适系统或 META root 下备份自己机器：

```bash
python xiaodu.py backup
python xiaodu.py fetch-tools
```

备份保存在 `work/backup/`；只有必要启动、锁配置、校准分区，不备份 userdata/system/vendor。`fetch-tools` 从 Magisk 官方下载固定 v30.7 并核对 SHA256，也支持 `--apk 自己下载的官方APK`。

## 3.2 构建自己的救援 Recovery

```bash
python xiaodu.py build-rescue --stock work/backup/recovery.img
```

它使用自己的原版 Recovery，保留其内核，做以下改动：

- 移除原厂自动升级/清数据的 recovery 程序及服务；
- 提供静态 shell，USB ADB 保留认证，只嵌入当前电脑的公钥；
- 使用已核对的 adbd 哈希及指令字节，跳过降到 shell 的分支；
- 私有密钥不会进入镜像；不开放 TCP ADB；
- 生成自己的救援标记，修改 Recovery 自身 SELinux 策略以允许维护；
- 重新签名，修正 AVB1 算法标识，并用 OpenSSL 独立验证。

策略修补时需短暂在现有 root 环境运行官方 magiskpolicy，暂存于 `/dev`，结束清理；本步骤不刷分区。二进制布局或证书不同会停止，不猜偏移。

写入并回读：

```bash
python xiaodu.py install-image recovery --image work/rescue-build/recovery-owner.img --apply
```

该命令先保留自己的写前副本，写入后核验哈希；写入或回读失败会尝试恢复。这无法替代断电情况下的外部救援。

## 3.3 实际走一遍独立 USB 救援

先启动监听，再按第一章接线顺序冷启动：

```bash
sudo .venv/bin/python xiaodu.py fastboot
```

同一个电脑普通用户核对并进入救援：

```bash
fastboot devices
fastboot getvar product
fastboot oem reboot-recovery
adb devices -l
python xiaodu.py rescue-check --from-fastboot
```

`product` 应为 `PUFFERX7`。只有**实际从 Preloader → Fastboot → 这份独立 Recovery**进入并确认 root，才使用 `--from-fastboot`。工具还会核对救援标记、硬件绑定和 Recovery 分区哈希，保存本机核验记录。

本机普通 `adb reboot bootloader` 不可靠，不用它替代这条已验证入口。救援不依赖正常 boot，但仍依赖 Preloader/LK 可工作。

## 3.4 修补并安装正常 boot

构建步骤在电脑离线运行，使用自己备份的、与实测版本一致的原厂 boot：

```bash
python xiaodu.py build-boot --stock work/backup/boot.img
```

工具保留原内核、verity 和加密选项，加入 Magisk，以及开机停止 `flash_recovery` 的规则，防止原厂覆盖独立救援。不会使用作者的已修补镜像，也不需要嵌入作者的公钥。

仍在已验证的独立救援中执行：

```bash
python xiaodu.py install-image boot --image work/boot-build/boot-magisk.img --apply
adb reboot
```

启动后安装官方 Magisk APK、检查权限：

```bash
adb install work/Magisk-v30.7.apk
adb shell /sbin/su -c id
python xiaodu.py verify
```

若面具要求授权 Shell，按屏幕提示授权该应用。其他 APP 不自动获得 root。不要立刻使用面具在线升级或重新覆盖已经验证的镜像。

本机原生开机的 su、模块、systemless 与 Zygisk 均验证过；**BL 在完成这一章时仍可能锁定**。

## 3.5 AVB1 为什么麻烦

本机接受相应测试证书签名的修改镜像，但仍检查签名格式。Magisk30.7 的签名代码可能沿用证书的 SHA1 算法元数据，而真正生成的是 SHA256 镜像签名。工具只从原版参照修正该元数据，再用 OpenSSL 独立核验签名、目标分区、长度、内核和证书，不能把“生成了文件”当成“机器肯定能启动”。
