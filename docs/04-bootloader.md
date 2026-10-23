# 4. 真正的 Bootloader 解锁：HACC + seccfg

前提：正常系统已有可调用 root，完整固件是 `DuerShow_MT8167s_v1.68.2.20250324172557685.R`，原厂 LK/LK2、内核及厂商模块与已核对版本一致。建议先按上一章建立独立救援。

## 4.1 原理

原厂 LK 读取 `seccfg` V4：

- 前28字节是7个小端整数，含锁状态；
- 后32字节是保护头部 SHA256 的硬件加密校验；
- 其余分区内容本次不动。

本机原状态 `lock_state=1`，解锁状态是 `3`。单改锁状态会使校验失效。常见软件 AES 变体没有匹配本机；成功方法是利用**已有 root**，临时从内核模块调用原厂 HACC user0，生成和原厂 LK 一致的校验。

没有提取硬件密钥，也没修改 LK 来伪报解锁。

## 4.2 检查版本

```bash
python xiaodu.py doctor
python xiaodu.py verify
```

程序用 [精确配置](../profiles/xdh29b1-1682.json) 同时检查完整固件、内核 release/version、boot 内核 SHA、LK/LK2 SHA、厂商模块 SHA 和当前内核符号地址。未知版本不继续，**不提供绕过这些条件的 force 开关**。

如果已解锁，不再写一次。不要因历史文件名含 UNFLASHED 就重刷。

## 4.3 生成自己的候选配置

```bash
python xiaodu.py bl-prepare --run-hacc
```

该命令有临时内核执行，尚未刷写分区：

1. 从当前机器读取 `seccfg` 和原厂模块 ABI 模板；
2. 临时读取内核函数地址，结束恢复原 `kptr_restrict`；
3. 生成包含**当前机器数据**的 ARM 探针，构建并加载临时模块；
4. 验证“旧密文解密＝旧头部 SHA256”；
5. 验证“重新加密旧头部 SHA256＝原密文”；
6. 计算新头部校验，再解密回验；
7. 卸载临时模块，删除设备暂存，只在自己电脑保存计划。

四项回验都通过才生成 `work/bl/plan.json`、`before.img`、`candidate.img`。候选仅改变锁字段和校验密文，其余字节保持。

原始实测还先做过不执行任何逻辑的空模块加载/卸载，再测试 HACC user1 与 user0；user1 回验不匹配，没有用于刷写。公开版使用已确认的 user0，仍每次回验，不以“加载成功”替代密码校验成功。

## 4.4 写入本机首扇区

确认上一命令通过后：

```bash
python xiaodu.py bl-install --apply
```

写入器核对稳定硬件绑定、计划与文件 SHA、当前原配置、变更范围，再只写首个 **512字节扇区**。原始实测实际有 **33字节**变化：锁状态1字节和32字节密文；其他设备实际变化字节数以自己的比较结果为准。

它不会清空 seccfg，不会写 LK/LK2、Preloader、GPT、FRP、userdata 或 eFuse。写入后设备端与主机端均回读校验；失败尝试恢复原首扇区。不会自动重启，也不能保证断电时自动恢复。

## 4.5 用原厂 Fastboot 核验，再回系统

先运行等待程序，再冷启动：

```bash
sudo .venv/bin/python xiaodu.py fastboot
```

同一电脑普通用户运行：

```bash
fastboot getvar product
fastboot getvar unlocked
fastboot getvar secure
```

原始实机成功响应：

```text
product: PUFFERX7
unlocked: yes
secure: no
```

随后：

```bash
fastboot continue
python xiaodu.py verify
```

原始实机正常系统为 `ro.boot.flash.locked=0`、`ro.boot.verifiedbootstate=orange`，Magisk su仍是uid0。

`verify` 只读取属性，不会修改属性来假装解锁。Android属性检查与原厂Fastboot核验都应完成。

## 4.6 不要误解解锁范围

- `secure:no` 是 LK 当前状态响应，不代表烧写或关闭芯片安全熔丝。
- 没有取消 BootROM→Preloader→LK 的全部信任链。
- 没有证明任意内核、任意 ROM 都能启动；镜像格式、驱动和硬件兼容仍要核对。
- 不要把别人的 `seccfg`、HACC 模块或固定地址拿来套用。
- 不提供“一键重新上锁”。锁回前必须核对当前 boot/recovery 是否仍符合锁定启动条件；有备份不等于随时可安全上锁。
