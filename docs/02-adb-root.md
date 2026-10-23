# 2. 正常 ADB、维护 root 与无线调试

## 2.1 在 META 写入当前电脑的公钥

先确认上一章 `meta-check` 通过。可先做必要小型备份：

```bash
python xiaodu.py backup
python xiaodu.py authorize --apply
```

`authorize` 只创建此前不存在的 `/data/misc/adb/adb_keys`：读取当前电脑 `~/.android/adbkey` 的**公钥**，写入后设置 `system:shell / 0640` 和原厂 SELinux 标签并核对哈希。不会上传、复制或公开私钥，不会关闭 ADB 认证。

如果设备已有 `adb_keys`，程序停止，**不会覆盖其他授权**。需要人工核对现有授权后再决定如何合并。

然后正常重启：

```bash
adb reboot
adb devices -l
python xiaodu.py doctor
```

正常 ADB 应是 `device`，普通 shell 通常仍为 `uid=2000`。这一步没有声称正常系统已经 root。

## 2.2 配置正常系统维护 root

在正常系统、普通 ADB shell 下运行：

```bash
python xiaodu.py root-setup --apply
python xiaodu.py root 'id'
```

原理：原厂 init 管理的 `bdft_server` 以 root 运行；音频测试准备阶段会读取 `/data/log/FactoryConfig` 中 `$TINYMIX_SPEAKER` 配置，执行对应命令。工具把这个入口指向固定维护分派脚本，提交和回读结果均放在 shell 私有目录。

脚本做了最小限制：

- 请求目录 `/data/local/tmp/x1s-toolkit` 为 `shell:shell / 0700`；
- 配置文件为 `root:shell / 0640`，并设置 immutable，避免可写父目录中的普通应用替换它；
- 拒绝覆盖已有 `FactoryConfig` 或已有工具目录；
- 命令完成后删除临时输入输出，不把上次命令长期留着。

`bdft audio -play /dev/null` 不播放音频，但会停止 tinyplay，所以不要和 tinyplay 音频测试同时运行。

这是正常系统维护入口，**不是 Magisk 应用授权管理器**，也没有自动给所有 APP root 权限。此时 BL 仍可锁定，boot/system/vendor 均未被本步骤改写。

## 2.3 开启认证无线 ADB

先连接正常 Wi-Fi，再运行：

```bash
python xiaodu.py wifi-adb --apply
```

该命令设置 TCP ADB 端口 5555 并重启 adbd，USB 会短暂断开。到机器的 Wi-Fi 设置或路由器查看设备 IP，执行：

```bash
adb connect 设备IP:5555
python xiaodu.py --serial 设备IP:5555 doctor
python xiaodu.py --serial 设备IP:5555 root 'id'
```

ADB 密钥认证继续保留，不把陌生电脑当作已授权。IP 由读者自己的路由器分配，不使用作者家中的固定地址。

## 2.4 维护入口如何移除

在它仍可用时依次执行：

```bash
python xiaodu.py root 'busybox chattr -i /data/log/FactoryConfig; rm /data/log/FactoryConfig'
adb shell setprop ctl.stop bdft_server
adb shell rm -rf /data/local/tmp/x1s-toolkit
```

先确认该文件确由本工具创建。不要用 `sys.bdft.server=0` 猜停服：本机原厂 rc 对该属性的处理不是普通布尔开关。移除维护入口不会移除已添加的 ADB 公钥。
