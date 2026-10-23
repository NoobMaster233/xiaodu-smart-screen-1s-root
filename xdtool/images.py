"""Build per-user boot/recovery images; only explicit install writes a partition."""
import json,re,secrets,shlex,shutil,struct,subprocess,urllib.request,zipfile
from pathlib import Path
from .common import ROOT,require,run,save,sha
from .verify_avb1 import verify
from .normalize_avb1 import normalize

MAGISK_SHA='e0d32d2123532860f97123d927b1bb86c4e08e6fd8a48bfc6b5bee0afae9ebd5'

def fetch(work,apk=None):
    work=Path(work);work.mkdir(parents=True,exist_ok=True)
    package=Path(apk) if apk else work/'Magisk-v30.7.apk'
    if not package.exists():
        require(apk is None,'指定的Magisk APK不存在。')
        print('从Magisk官方Release下载固定v30.7…',flush=True)
        with urllib.request.urlopen('https://github.com/topjohnwu/Magisk/releases/download/v30.7/Magisk-v30.7.apk',timeout=60) as source:package.write_bytes(source.read())
    require(sha(package.read_bytes())==MAGISK_SHA,'Magisk APK SHA256不符；拒绝解压或执行。')
    canonical=work/'Magisk-v30.7.apk'
    if package.resolve()!=canonical.resolve():shutil.copyfile(package,canonical)
    tools=work/'magisk';tools.mkdir(exist_ok=True)
    mapping={'magiskinit':'lib/armeabi-v7a/libmagiskinit.so','magisk':'lib/armeabi-v7a/libmagisk.so','magiskboot':'lib/armeabi-v7a/libmagiskboot.so','magiskpolicy':'lib/armeabi-v7a/libmagiskpolicy.so','busybox':'lib/armeabi-v7a/libbusybox.so','init-ld':'lib/armeabi-v7a/libinit-ld.so','stub.apk':'assets/stub.apk'}
    with zipfile.ZipFile(package) as z:
        for dest,source in mapping.items():
            (tools/dest).write_bytes(z.read(source));(tools/dest).chmod(0o755)
        (tools/'assets').mkdir(exist_ok=True)
        for name in z.namelist():
            if name.startswith('assets/') and name.endswith('.sh') and '/' not in name[len('assets/'):]:
                (tools/name).write_bytes(z.read(name))
    return tools

def context(work,tag):
    folder=Path(work)/tag;folder.mkdir(parents=True,exist_ok=False,mode=0o700)
    tools=Path(work)/'magisk'
    require((tools/'magiskboot').exists(),'先运行 fetch-tools。')
    return folder,tools

def mb(tools,folder,*args):
    return run(['qemu-arm',tools/'magiskboot',*args],cwd=folder,timeout=120)

def build_boot(work,stock):
    profile=json.loads((ROOT/'profiles/xdh29b1-1682.json').read_text());stock=Path(stock).resolve()
    require(sha(stock.read_bytes()) in profile['boot_original_sha256'],'只自动处理核对过的官方1.68.2原版boot；不要给已修补boot重复修补。')
    original=verify(stock,'/boot');folder,tools=context(work,'boot-build');tools=tools.resolve()
    for name in ('magiskinit','magisk','init-ld','stub.apk'):shutil.copyfile(tools/name,folder/name)
    wrapper=folder/'magiskboot';wrapper.write_text('#!/bin/sh\nexec qemu-arm '+shlex.quote(str(tools/'magiskboot'))+' "$@"\n');wrapper.chmod(0o755)
    driver='''set -e
SOURCEDMODE=true
BOOTMODE=true
KEEPVERITY=true
KEEPFORCEENCRYPT=true
PATCHVBMETAFLAG=false
PREINITDEVICE=userdata
RECOVERYMODE=false
LEGACYSAR=false
ui_print() { printf '%s\\n' "$*"; }
abort() { printf '%s\\n' "$*" >&2; exit 1; }
set -- STOCK
. SCRIPT
'''.replace('STOCK',shlex.quote(str(stock))).replace('SCRIPT',shlex.quote(str(tools/'assets/boot_patch.sh')))
    log=run(['bash','-c',driver],cwd=folder,timeout=150);(folder/'patch.log').write_bytes(log)
    (folder/'keep-rescue.rc').write_text('on post-fs-data\n    stop flash_recovery\n')
    mb(tools,folder,'cpio','ramdisk.cpio','add 0644 overlay.d/keep-rescue.rc keep-rescue.rc')
    (folder/'kernel').unlink(missing_ok=True)
    mb(tools,folder,'repack',str(stock),'boot.raw.img');mb(tools,folder,'sign','boot.raw.img','/boot')
    output=folder/'boot-magisk.img';proof=normalize(folder/'boot.raw.img',stock,output,16777216)
    require(proof['kernel_sha256']==original['kernel_sha256'],'内核发生了变化。')
    proof.update(kind='boot',stock_sha256=sha(stock.read_bytes()),source_kernel_sha256=original['kernel_sha256'],built_by='x1s-toolkit-v0.1.0',contains_owner_key=False)
    save(folder/'build.json',proof)
    return str(output)

def build_rescue(d,stock):
    stock=Path(stock).resolve();original=verify(stock,'/recovery')
    require(original['certificate_sha256']=='8ad127abae8285b582ea36745f220ab8fe397ffb3b068df19ca22d122c7b3b86','Recovery证书未适配。')
    folder,tools=context(d.work,'rescue-build');tools=tools.resolve()
    mb(tools,folder,'unpack',str(stock))
    def extract(name,output):
        mb(tools,folder,'cpio','ramdisk.cpio','extract '+name+' '+output)
        return (folder/output).read_bytes()
    props=extract('prop.default','prop.default').decode()
    replacements={'ro.secure':'0','ro.adb.secure':'1','ro.debuggable':'1','ro.testmode':'NO','service.adb.root':'1','persist.sys.usb.config':'adb','service.adb.tcp.port':'0','persist.adb.tcp.port':'0','ro.serialno':'X1S-OWNER-RESCUE','ro.xiaodu.rescue':'x1s-toolkit-v0.1.0'}
    for key,value in replacements.items():
        props=re.sub(r'^'+re.escape(key)+r'=.*$',key+'='+value,props,flags=re.M) if re.search(r'^'+re.escape(key)+'=',props,re.M) else props+'\n'+key+'='+value
    (folder/'prop.default').write_text(props+'\n')
    init=extract('init.rc','init.rc').decode();require('service recovery /sbin/recovery' in init,'原厂recovery服务布局未适配。')
    init=re.sub(r'\nservice recovery /sbin/recovery\n(?:[ \t].*\n|\n)*','\n',init)
    init=init.replace('service charger /charger -r\n','service charger /charger -r\n    disabled\n').replace('--root_seclabel=u:r:su:s0','--root_seclabel=u:r:adbd:s0').replace('D001','D005')
    init+='\non boot\n    start adbd\n';(folder/'init.rc').write_text(init)
    usb=extract('init.recovery.mt8167.rc','init.recovery.mt8167.rc').decode().replace('0xd001','0xd005');(folder/'init.recovery.mt8167.rc').write_text(usb)
    adbd=extract('sbin/adbd','adbd.stock')
    require(sha(adbd)=='a51c189900c495e0588db6dbc0fd0be27e5e1dcb76b2eeed4500b7c0f466fffd' and adbd[0x3a24:0x3a26]==bytes.fromhex('cfb3'),'adbd二进制未适配，禁止按固定偏移修补。')
    old=b'/system/misc/adb_keys\0';require(adbd.count(old)==1,'adbd密钥路径不匹配。')
    modified=bytearray(adbd.replace(old,b'/xiaodu/adb_keys\0'.ljust(len(old),b'\0')));modified[0x3a24:0x3a26]=bytes.fromhex('00bf');(folder/'adbd.owner').write_bytes(modified)
    key=run([d.adb,'pubkey',str(Path.home()/'.android/adbkey')]).split()[0]+b' xiaodu-owner\n';(folder/'owner.pub').write_bytes(key)
    (folder/'marker').write_text('owner-recovery-only\n');(folder/'build-marker').write_text('x1s-toolkit-v0.1.0\n')
    # magiskpolicy needs Android's linker. Execute it only in the existing root environment, not on Linux.
    extract('sepolicy','sepolicy.original')
    stage='/dev/x1s-policy-'+secrets.token_hex(4)
    d.root('mkdir '+stage+' && chmod 700 '+stage)
    try:
        for local,name in [(tools/'magiskpolicy','magiskpolicy'),(folder/'sepolicy.original','sepolicy')]:d.root('cat > '+stage+'/'+name,data=local.read_bytes())
        d.root('chmod 700 '+stage+'/magiskpolicy; '+stage+'/magiskpolicy --load '+stage+'/sepolicy --save '+stage+'/patched '+shlex.quote('permissive adbd')+' '+shlex.quote('permissive shell'))
        (folder/'sepolicy.owner').write_bytes(d.root('cat '+stage+'/patched',binary=True))
    finally:d.root('rm -rf '+stage)
    require((folder/'sepolicy.owner').stat().st_size>500000,'策略输出异常。')
    mb(tools,folder,'cpio','ramdisk.cpio','rm sbin/recovery','add 0644 prop.default prop.default','add 0750 init.rc init.rc','add 0750 init.recovery.mt8167.rc init.recovery.mt8167.rc','add 0644 sepolicy sepolicy.owner','add 0755 sbin/adbd adbd.owner',f'add 0755 sbin/busybox {tools/"busybox"}','mkdir 0755 system/bin',f'add 0755 system/bin/sh {tools/"busybox"}','mkdir 0755 xiaodu','add 0644 xiaodu/adb_keys owner.pub','mkdir 0755 cache','add 0400 cache/factory_adb_tag marker','add 0644 xiaodu-rescue-build build-marker')
    (folder/'kernel').unlink();mb(tools,folder,'repack',str(stock),'rescue.raw.img');mb(tools,folder,'sign','rescue.raw.img','/recovery')
    output=folder/'recovery-owner.img';proof=normalize(folder/'rescue.raw.img',stock,output,16777216)
    require(proof['kernel_sha256']==original['kernel_sha256'],'Recovery内核发生变化。')
    proof.update(kind='recovery',stock_sha256=sha(stock.read_bytes()),source_kernel_sha256=original['kernel_sha256'],built_by='x1s-toolkit-v0.1.0',binding=d.binding(),owner_public_key_sha256=sha(key),usb_authentication=True,tcp_adb=False,vendor_recovery_removed=True)
    save(folder/'build.json',proof)
    return str(output)


def install(d,kind,image,apply=False):
    require(apply,'实际写入需要 --apply。')
    image=Path(image).resolve();proof=json.loads((image.parent/'build.json').read_text());data=image.read_bytes();live=d.read_block(kind)
    verified=verify(image,'/'+kind)
    require(proof['kind']==kind and proof['built_by']=='x1s-toolkit-v0.1.0' and proof['image_sha256']==sha(data),'只接受本工具生成且哈希匹配的镜像。')
    require(len(data)==len(live)==16777216,'分区或镜像长度不匹配。')
    live_file=d.work/(kind+'-before-install.img');require(not live_file.exists(),'该写前备份已存在，拒绝覆盖；核对上次记录。');live_file.write_bytes(live)
    live_verified=verify(live_file,'/'+kind)
    require(verified['kernel_sha256']==live_verified['kernel_sha256'] and verified['certificate_sha256']==live_verified['certificate_sha256'],'候选镜像与当前分区的内核/证书不匹配。')
    if kind=='recovery':require(proof['binding']==d.binding(),'救援镜像不属于当前机器。')
    else:
        gate=json.loads((d.work/'rescue-verified.json').read_text())
        require(gate['binding']==d.binding() and gate['independent_fastboot_entry_confirmed'] is True,'先实际从Fastboot进入独立救援，再运行 rescue-check --from-fastboot。')
        require(d.shell('getprop ro.xiaodu.rescue').strip()=='x1s-toolkit-v0.1.0','boot只能在已验证的本工具救援环境中写入。')
        require(d.root('id').startswith('uid=0('),'救援root未确认。')
        # Native Magisk helpers, as used in the actual installation.
        d.root('mountpoint -q /data || /sbin/busybox mount -t ext4 -o rw,noatime,nosuid,nodev /dev/block/platform/bootdevice/by-name/userdata /data; mkdir -p /data/adb/magisk; chmod 700 /data/adb')
        tools=d.work/'magisk'
        for local in [*(tools/x for x in ('magisk','magiskinit','magiskboot','magiskpolicy','busybox','init-ld')),*list((tools/'assets').glob('*.sh'))]:
            d.root('cat > /data/adb/magisk/'+local.name+' && chmod 755 /data/adb/magisk/'+local.name,data=local.read_bytes())
    stage='/dev/x1s-image-'+secrets.token_hex(4);partition=d.block(kind)
    # /dev is tmpfs; no firmware or owner image is distributed in the public package.
    d.root('cat > '+stage+'.new && chmod 600 '+stage+'.new',data=data)
    d.root('cat > '+stage+'.old && chmod 600 '+stage+'.old',data=live)
    output=d.root(f'''set -eu
bb={shlex.quote(str('/sbin/busybox' if d.shell('getprop ro.xiaodu.rescue').strip() else 'busybox'))}
trap 'rm -f {stage}.old {stage}.new' EXIT HUP INT TERM
[ "$($bb sha256sum {partition} | $bb cut -d ' ' -f 1)" = {sha(live)} ]
[ "$($bb sha256sum {stage}.new | $bb cut -d ' ' -f 1)" = {sha(data)} ]
rc=0
$bb dd if={stage}.new of={partition} bs=4096 conv=fsync 2>/dev/null || rc=$?
sync
actual=$($bb sha256sum {partition} | $bb cut -d ' ' -f 1)
if [ "$rc" != 0 ] || [ "$actual" != {sha(data)} ]; then
 $bb dd if={stage}.old of={partition} bs=4096 conv=fsync 2>/dev/null
 sync
 exit 74
fi
echo IMAGE_WRITE_VERIFIED
''')
    require(d.read_block(kind)==data,'主机回读未匹配，停止。')
    result={'partition':kind,'before_sha256':sha(live),'candidate_sha256':sha(data),'readback_verified':True,'rebooted':False,'output':output};save(d.work/(kind+'-install-result.json'),result)
    return result
