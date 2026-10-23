#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ "$(id -u)" -eq 0 ]; then
  apt-get update
  apt-get install -y python3 python3-venv libusb-1.0-0 adb fastboot qemu-user binutils-arm-linux-gnueabi openssl usbutils
else
  sudo apt-get update
  sudo apt-get install -y python3 python3-venv libusb-1.0-0 adb fastboot qemu-user binutils-arm-linux-gnueabi openssl usbutils
fi
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
printf '\n准备完成。普通命令：.venv/bin/python xiaodu.py --help\nUSB捕获需要USB权限；必要时：sudo .venv/bin/python xiaodu.py meta\n不要把其他步骤全部改成sudo，ADB公钥应使用同一个电脑用户。\n'
