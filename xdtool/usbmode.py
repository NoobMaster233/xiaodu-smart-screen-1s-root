"""Linux USB selector: same READY/CDC sequence as the real-device experiment."""
import struct,sys,time
from pathlib import Path
from .common import require


def select(mode,port=None,seconds=180):
    require(sys.platform.startswith('linux'),'USB 启动捕获首版只支持 Linux；Windows/WSL 的 USB 驱动路径没有验证。')
    import usb.core,usb.util
    require(mode in ('METAMETA','FASTBOOT'),'不支持的模式')
    if port: require(bool(__import__('re').fullmatch(r'\d+-\d+(?:\.\d+)*',port)),'USB 物理端口格式应如 1-5 或 1-2.3')
    root=Path('/sys/bus/usb/devices')
    def candidates():
        found=[]
        for node in ([root/port] if port else root.iterdir()):
            try:
                if (node/'idVendor').read_text().strip()=='0e8d' and (node/'idProduct').read_text().strip() in ('2000','0003'):
                    found.append((node.name,int((node/'busnum').read_text()),int((node/'devnum').read_text()),(node/'idProduct').read_text().strip()))
            except (OSError,ValueError):pass
        return found
    baseline=set(candidates())
    print('已开始等待。请拔设备电源和USB，等10秒；先接USB，等5秒，再接原装电源。',flush=True)
    deadline=time.monotonic()+seconds;item=None
    while time.monotonic()<deadline:
        fresh=[x for x in candidates() if x not in baseline]
        require(len(fresh)<=1,'同时发现多台MTK设备，请拔掉其他设备或明确 --usb-port。')
        if fresh:item=fresh[0];break
        time.sleep(.01)
    require(item is not None,'等待超时；确认数据线支持传输、原装电源接好，再重新运行。')
    port,bus,address,pid=item
    require(pid=='2000','当前是 BootROM，不是已验证的 Preloader READY 路径；未发送下载代理或刷写命令。')
    device=usb.core.find(idVendor=0x0e8d,idProduct=0x2000,custom_match=lambda d:d.bus==bus and d.address==address)
    require(device is not None,'USB设备已经离开，请重新冷启动。')
    claimed=[];detached=[]
    try:
        cfg=device.get_active_configuration();pairs=[];controls=[]
        for interface in cfg:
            if interface.bInterfaceClass==2:controls.append(interface.bInterfaceNumber)
            ins=[e for e in interface if e.bmAttributes&3==2 and e.bEndpointAddress&0x80]
            outs=[e for e in interface if e.bmAttributes&3==2 and not e.bEndpointAddress&0x80]
            if ins and outs:pairs.append((interface,ins[0],outs[0]))
        require(pairs,'找不到USB bulk端点。')
        pairs.sort(key=lambda x:x[0].bInterfaceClass!=10)
        interface,epin,epout=pairs[0];control=controls[0] if controls else interface.bInterfaceNumber
        for n in dict.fromkeys((control,interface.bInterfaceNumber)):
            if device.is_kernel_driver_active(n):device.detach_kernel_driver(n);detached.append(n)
            usb.util.claim_interface(device,n);claimed.append(n)
        for request,value,payload in ((0x20,0,struct.pack('<IBBB',921600,0,0,8)),(0x22,2,b'')):
            try:device.ctrl_transfer(0x21,request,value,control,payload,timeout=100)
            except usb.core.USBError:pass
        ready=False;until=time.monotonic()+1.2
        while time.monotonic()<until:
            try:
                if bytes(epin.read(512,timeout=100))==b'READY':ready=True;break
            except usb.core.USBTimeoutError:pass
        require(ready,'未收到READY；没有发送模式指令，请重新冷启动。')
        epout.write(mode.encode('ascii'),timeout=100)
        if mode=='FASTBOOT':
            accepted=False
            for _ in range(5):
                response=bytes(epin.read(512,timeout=200))
                if response==b'READY':continue
                accepted=response==b'TOOBTSAF';break
            require(accepted,'未收到FASTBOOT确认；请检查USB状态，不要假定已经进入。')
            try:epout.write(b'DISCONNECT',timeout=100)
            except usb.core.USBError:pass
        # Verified META path intentionally sends METAMETA only, no optional parameter packets.
        print('已发送 '+mode+'。'+('等待META启动后执行 meta-check。' if mode=='METAMETA' else '请用 fastboot devices 核实；进入Fastboot不等于解锁。'))
        return {'physical_port':port,'mode_sent':mode,'storage_written':False}
    finally:
        for n in reversed(claimed):
            try:usb.util.release_interface(device,n)
            except usb.core.USBError:pass
        for n in detached:
            try:device.attach_kernel_driver(n)
            except usb.core.USBError:pass
        usb.util.dispose_resources(device)
