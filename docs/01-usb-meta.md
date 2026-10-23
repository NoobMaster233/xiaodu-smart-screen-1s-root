# 1. USB 接线与 META root

目标是通过已有 USB 接口选中维护启动模式。不拆屏蔽罩、不焊线、不短接测试点，不需要音量加减键。

## 1.1 先启动电脑上的等待程序

```bash
sudo .venv/bin/python xiaodu.py meta
```

看到“已开始等待”后再操作机器：

1. 拔小度电源和 USB，等 **10 秒**。
2. 先插 **USB 数据线**，另一端接电脑。
3. 等 **5 秒**。
4. 接 **小度原装电源**，不要按实体键。

电脑会捕获 Preloader 的 `READY`，发送 `METAMETA`。已验证的路线只发送这 8 个 ASCII 字节，不补发网上其他 META 参数包。没有发送擦除、刷写、NVRAM 或下载代理命令。

只有一台 MTK 设备时可自动识别。需要限定物理端口时：

```bash
sudo .venv/bin/python xiaodu.py meta --usb-port 1-5
```

`1-5` 是格式例子，不能直接假定电脑也是这个端口。Linux 可用 `lsusb -t` 和 `/sys/bus/usb/devices/` 核对。

## 1.2 进入后必须核验

用后续一直使用的同一个普通电脑用户运行：

```bash
adb start-server
adb devices -l
python xiaodu.py meta-check
```

通过条件同时包括：

- 型号 `XDH-29-B1`；
- 内核启动参数包含 `android.testmetamode=meta`；
- `id` 返回 `uid=0(root)`。

部分旧工厂镜像进入 META 后先是 shell。`meta-check` 会在确认 META 后请求 `adb root`，USB 可能重新枚举；稍等后重新执行一次 `meta-check`。

USB `0e8d:200e` 是这台机器的 META 身份线索，**不能只看到 USB 变化就当作已拿 root**。若 ADB 没刷新，可在没有其他 ADB 任务时手动 `adb kill-server`、`adb start-server`，再核验。

## 1.3 已排除的路线

- `FACTFACT`：本机能进入工厂诊断，但 ADB 当时仍 unauthorized，不能把它写成成功 root 方法。
- 现成通用 MTK 下载代理：本机此前被签名校验拒绝，未用于成功路线。
- BootROM：本工具若看到 BootROM 会停止，不自动尝试漏洞、DA 或任意内存写入。

这一阶段的 root 只说明 META 有最高权限。下一章把正常系统 ADB 接通。
