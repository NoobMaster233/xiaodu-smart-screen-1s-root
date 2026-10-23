"""ADB helpers. No personal addresses, keys or device snapshots are embedded."""
import hashlib,json,os,re,shlex,shutil,subprocess,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
MODEL='XDH-29-B1'

def require(ok,message):
    if not ok: raise RuntimeError(message)

def sha(data): return hashlib.sha256(data).hexdigest()

def save(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');path.chmod(0o600)

def run(argv,**kwargs):
    r=subprocess.run(list(map(str,argv)),capture_output=True,timeout=kwargs.pop('timeout',30),**kwargs)
    if r.returncode:
        raise RuntimeError('命令失败：'+str(argv[0])+'\n'+r.stderr.decode(errors='replace')[-1600:])
    return r.stdout

class Device:
    def __init__(self,serial=None,work='work',adb=None):
        self.adb=adb or os.environ.get('ADB') or shutil.which('adb')
        require(self.adb,'找不到 adb。先运行 bash scripts/setup-linux.sh，或把官方 Platform-Tools 加入 PATH。')
        self.work=Path(work).resolve();self.work.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.work.chmod(0o700)
        if serial and ':' in serial: run([self.adb,'connect',serial],timeout=8)
        if not serial:
            lines=run([self.adb,'devices','-l']).decode().splitlines()[1:]
            devices=[x.split()[0] for x in lines if len(x.split())>1 and x.split()[1]=='device']
            require(len(devices)==1,'需要且只能有一台已授权设备；多台时使用 --serial 序列号，未授权时先完成 META。')
            serial=devices[0]
        self.serial=serial;self.prefix=[self.adb,'-s',serial]
        require(self.shell('getprop ro.product.model').strip()==MODEL,'型号不是小度智能屏1S XDH-29-B1，停止。')
        self._root=None

    def shell(self,command,data=None,binary=False):
        out=run(self.prefix+(['exec-out'] if binary else ['shell','-T'])+[command],input=data)
        return out if binary else out.decode(errors='replace')

    def root(self,command,data=None,binary=False):
        if self._root is None:
            if self.shell('id').startswith('uid=0('):self._root='direct'
            else:
                try: ok=self.shell('/sbin/su -c id').startswith('uid=0(')
                except RuntimeError:ok=False
                if ok:self._root='su'
                else:
                    require(self.shell('test -f /data/local/tmp/x1s-toolkit/dispatch.sh && head -n 1 /data/local/tmp/x1s-toolkit/dispatch.sh').startswith('# x1s-toolkit'),'需要META root、已授权Magisk su或先运行 root-setup。')
                    self._root='bdft'
        if self._root=='bdft':return self.bdft(command,data,binary)
        if self._root=='direct' and self.shell('getprop ro.xiaodu.rescue').strip()=='x1s-toolkit-v0.1.0':
            command='ASH_STANDALONE=1 /sbin/busybox sh -c '+shlex.quote(command)
        elif self._root=='su':command='/sbin/su -c '+shlex.quote(command)
        return self.shell(command,data,binary)

    def start_bdft(self):
        self.shell('setprop ctl.start bdft_server')
        until=time.monotonic()+5
        while self.shell('getprop init.svc.bdft_server').strip()!='running':
            require(time.monotonic()<until,'bdft服务启动超时。')
            time.sleep(.1)

    def bdft(self,command,data=None,binary=False):
        import fcntl
        remote='/data/local/tmp/x1s-toolkit'
        with (self.work/'root.lock').open('a') as handle:
            fcntl.flock(handle,fcntl.LOCK_EX)
            require(self.shell("stat -c '%u:%g:%a' /data/log/FactoryConfig").strip()=='0:2000:640','FactoryConfig权限不匹配。')
            require('i' in self.shell('busybox lsattr /data/log/FactoryConfig').split()[0],'FactoryConfig保护标记丢失，拒绝执行。')
            self.shell('rm -f '+remote+'/exitcode')
            if data is not None:self.shell('umask 077; cat > '+remote+'/input.bin',data=data)
            self.shell('umask 077; cat > '+remote+'/request.sh',data=(('(\n'+command+'\n) < '+remote+'/input.bin' if data is not None else command)+'\n').encode())
            self.start_bdft()
            self.shell('bdft audio -play /dev/null')
            until=time.monotonic()+5
            while time.monotonic()<until:
                try:
                    code=int(self.shell('cat '+remote+'/exitcode').strip());break
                except (RuntimeError,ValueError):time.sleep(.1)
            else:raise RuntimeError('维护请求未结束；不要覆盖请求文件，先检查设备。')
            out=self.shell('cat '+remote+'/stdout',binary=True)
            err=self.shell('cat '+remote+'/stderr')
            self.shell('rm -f '+remote+'/stdout '+remote+'/stderr '+remote+'/exitcode '+remote+'/input.bin; printf : > '+remote+'/request.sh')
            require(code==0,'root命令失败：'+err[-1000:])
            return out if binary else out.decode(errors='replace')

    def info(self):
        keys=['ro.product.model','ro.build.display.id','ro.product.cpu.abi','ro.boot.flash.locked','ro.boot.verifiedbootstate']
        result={k:self.shell('getprop '+k).strip() for k in keys}
        result['adb_identity']=self.shell('id').strip()
        return result

    def binding(self):
        # Local only: binds a write plan to its source hardware without putting IDs into the public repository.
        cid=self.root('cat /sys/block/mmcblk0/device/cid').strip()
        require(bool(re.fullmatch(r'[0-9a-fA-F]{32}',cid)),'无法读取稳定的eMMC硬件标识；拒绝绑定写入计划。')
        return sha(cid.lower().encode())

    def block(self,name):
        require(bool(re.fullmatch(r'[a-zA-Z0-9_]+',name)),'分区名不合法')
        out=self.root('readlink -f /dev/block/platform/bootdevice/by-name/'+name).strip()
        require(bool(re.fullmatch(r'/dev/block/mmcblk0p[0-9]+',out)),'未找到该分区：'+name)
        return out

    def read_block(self,name):
        return self.root('cat '+self.block(name),binary=True)

    def push(self,local,remote): run(self.prefix+['push',local,remote],timeout=90)
