"""Chinese CLI for the documented XDH-29-B1 workflow."""
import argparse,base64,json,os,re,shlex,shutil,struct,sys
from pathlib import Path
from .common import Device,ROOT,require,run,save,sha

REMOTE='/data/local/tmp/x1s-toolkit'

def root_setup(d,apply):
    require(apply,'安装维护入口需要 --apply。')
    require(d.shell('id').startswith('uid=2000('),'root-setup应在正常系统普通ADB shell下运行，不在META或救援里安装。')
    require('android.testmetamode=meta' not in d.shell('cat /proc/cmdline'),'先正常启动后再配置维护入口。')
    # This deliberately refuses the owner's pre-existing private setup or another tool's FactoryConfig.
    d.shell('test ! -e /data/log/FactoryConfig && test ! -e '+REMOTE)
    dispatch='''# x1s-toolkit dispatch v0.1.0
set -u
r=/data/local/tmp/x1s-toolkit
[ "$(id -u)" = 0 ] || exit 71
[ "$(stat -c '%u:%g:%a' "$r")" = 2000:2000:700 ] || exit 72
[ ! -L "$r/request.sh" ] || exit 73
rc=0
/system/bin/sh "$r/request.sh" > "$r/stdout" 2> "$r/stderr" || rc=$?
printf '%s\\n' "$rc" > "$r/exitcode"
chown shell:shell "$r/stdout" "$r/stderr" "$r/exitcode"
chmod 600 "$r/stdout" "$r/stderr" "$r/exitcode"
'''
    d.shell('umask 077; mkdir '+REMOTE+'; chmod 700 '+REMOTE)
    d.shell('cat > '+REMOTE+'/dispatch.sh; chmod 700 '+REMOTE+'/dispatch.sh',data=dispatch.encode())
    config='$TINYMIX_SPEAKER\n/system/bin/sh '+REMOTE+'/dispatch.sh\n'
    d.shell('umask 077; cat > /data/log/FactoryConfig',data=config.encode())
    initial='''set -e
chown root:shell /data/log/FactoryConfig
chmod 640 /data/log/FactoryConfig
busybox chattr +i /data/log/FactoryConfig
id
'''
    d.shell('umask 077; cat > '+REMOTE+'/request.sh',data=initial.encode())
    d.start_bdft()
    d.shell('bdft audio -play /dev/null')
    require(d.shell('cat '+REMOTE+'/exitcode').strip()=='0','维护入口初始化失败，先核对设备，不覆盖已有配置。')
    require(d.root('id').startswith('uid=0('),'维护root未验证。')
    print('正常系统维护root已验证。不会自动装面具、写boot或解锁BL。')

def authorize(d,apply):
    require(apply,'写入当前电脑公钥需要 --apply。')
    require('android.testmetamode=meta' in d.shell('cat /proc/cmdline'),'请先进入META维护模式。')
    require(d.shell('id').startswith('uid=0('),'META还未取得root；先运行 meta-check。')
    d.shell('test ! -e /data/misc/adb/adb_keys && test ! -e /data/misc/adb/adb_keys.x1s-stage')
    key=run([d.adb,'pubkey',str(Path.home()/'.android/adbkey')]).split()[0]+b' xiaodu-owner\n'
    raw=base64.b64decode(key.split()[0],validate=True)
    require(len(raw)==524 and struct.unpack_from('<I',raw)[0]==64,'ADB公钥格式错误。')
    stage='/data/misc/adb/adb_keys.x1s-stage'
    d.shell('umask 077; cat > '+stage,data=key)
    d.shell('chown system:shell '+stage+'; chmod 640 '+stage+'; restorecon '+stage)
    require(d.shell('sha256sum '+stage).split()[0]==sha(key),'暂存公钥哈希不符。')
    require('u:object_r:adb_keys_file:s0' in d.shell('ls -lZ '+stage),'公钥SELinux标签不符。')
    d.shell('mv '+stage+' /data/misc/adb/adb_keys')
    require(d.shell('sha256sum /data/misc/adb/adb_keys').split()[0]==sha(key),'公钥回读不符。')
    print('已写入当前电脑的公钥；认证仍开启。正常重启后检查 adb devices。')

def backup(d):
    dest=d.work/'backup';dest.mkdir(mode=0o700,exist_ok=False)
    result={'binding':d.binding(),'files':{},'scope':'small boot/recovery/lock/calibration partitions only; no userdata/system/vendor'}
    for name in ('boot','recovery','seccfg','lk','lk2','nvram','nvdata','proinfo','protect1','protect2'):
        try:part=d.block(name)
        except RuntimeError:
            if name in ('boot','recovery','seccfg','lk','lk2'):raise
            print('跳过不存在的可选校准分区：',name);continue
        size=int(d.root('blockdev --getsize64 '+part).strip())
        require(0<size<=64*1024*1024,'分区大小超出小型备份上限：'+name)
        data=d.root('cat '+part,binary=True);require(len(data)==size,'备份长度错误：'+name)
        file=dest/(name+'.img');file.write_bytes(data);file.chmod(0o600)
        require(d.root('sha256sum '+part).split()[0]==sha(data),'备份哈希不匹配：'+name)
        result['files'][file.name]={'bytes':size,'sha256':sha(data)}
        print('已核对',file.name,size,'字节')
        save(dest/'manifest.json',result)
    return result

def doctor(d):
    info=d.info();info['host_dependencies']={name:bool(shutil.which(name)) for name in ('adb','fastboot','qemu-arm','openssl','arm-linux-gnueabi-as','arm-linux-gnueabi-objcopy')}
    info['bl_profile_matches_firmware']=info['ro.build.display.id']=='DuerShow_MT8167s_v1.68.2.20250324172557685.R'
    info['host_dependencies']['adb']=Path(d.adb).is_file() or bool(shutil.which(d.adb))
    save(d.work/'doctor.json',info)
    print(json.dumps(info,ensure_ascii=False,indent=2))
    return info

def main(argv=None):
    require(__debug__,'不要使用python -O运行本工具。')
    p=argparse.ArgumentParser(description='小度智能屏1S XDH-29-B1：META、root、Magisk与BL工具。默认不刷分区。')
    p.add_argument('--serial',help='ADB序列号或IP:端口；只接一台已授权设备时可省略')
    p.add_argument('--adb',help='adb可执行文件路径')
    p.add_argument('--work',default='work',help='仅保存在本机的私有工作目录，默认work')
    subs=p.add_subparsers(dest='action',required=True)
    subs.add_parser('doctor',help='只读检查型号、固件、权限和主机依赖')
    for action,mode in [('meta','METAMETA'),('fastboot','FASTBOOT')]:
        q=subs.add_parser(action,help='等待USB冷启动并发送'+mode+'；不刷分区')
        q.add_argument('--usb-port',help='Linux物理USB端口如1-5；省略时只允许一个新MTK设备')
        q.add_argument('--seconds',type=int,default=180)
    subs.add_parser('meta-check',help='验证META模式；必要时请求该模式内的adb root')
    for action,desc in [('authorize','在META root中写入当前电脑ADB公钥'),('root-setup','配置原厂bdft正常系统维护root')]:
        q=subs.add_parser(action,help=desc);q.add_argument('--apply',action='store_true')
    q=subs.add_parser('root',help='通过已有维护入口执行一条root命令，不播放声音');q.add_argument('command')
    subs.add_parser('backup',help='备份本机小型启动、锁配置与校准分区；不备份userdata')
    q=subs.add_parser('wifi-adb',help='开启保留密钥认证的无线ADB');q.add_argument('--apply',action='store_true')
    q=subs.add_parser('fetch-tools',help='下载并校验固定Magisk30.7，不连接设备');q.add_argument('--apk',help='也可使用自己下载的官方APK')
    for action,desc in [('build-boot','离线修补已核对的1.68.2原版boot'),('build-rescue','用自己的原版Recovery和公钥构建独立救援')]:
        q=subs.add_parser(action,help=desc);q.add_argument('--stock',required=True,type=Path)
    q=subs.add_parser('install-image',help='明确写入本工具生成的boot或recovery，保存写前副本并回读')
    q.add_argument('kind',choices=['boot','recovery']);q.add_argument('--image',type=Path,required=True);q.add_argument('--apply',action='store_true')
    q=subs.add_parser('rescue-check',help='在独立USB救援中核验root和镜像；不写分区');q.add_argument('--from-fastboot',action='store_true',help='仅在本人实际从FASTBOOT进入本工具救援后使用')
    q=subs.add_parser('bl-prepare',help='校验精确固件，临时运行HACC模块，生成本机解锁计划；不刷分区');q.add_argument('--run-hacc',action='store_true')
    q=subs.add_parser('bl-install',help='仅写已回验的本机seccfg首扇区并回读');q.add_argument('--apply',action='store_true')
    subs.add_parser('verify',help='只读核验root、BL属性；不重启、不写入')
    a=p.parse_args(argv)
    if a.action in ('meta','fastboot'):
        from .usbmode import select
        require(1<=a.seconds<=3600,'--seconds范围1..3600')
        return select('METAMETA' if a.action=='meta' else 'FASTBOOT',a.usb_port,a.seconds)
    if a.action=='fetch-tools':
        from .images import fetch
        print(fetch(a.work,a.apk));return
    if a.action=='build-boot':
        from .images import build_boot
        print(build_boot(a.work,a.stock));return
    d=Device(a.serial,a.work,a.adb)
    if a.action=='doctor':return doctor(d)
    if a.action=='meta-check':
        require('android.testmetamode=meta' in d.shell('cat /proc/cmdline'),'不是META，停止。')
        if not d.shell('id').startswith('uid=0('):
            print(run(d.prefix+['root']).decode());print('adbd可能重新枚举；请稍等后重新运行 meta-check。');return
        print('META root核验通过：'+d.shell('id').strip());return
    if a.action=='authorize':return authorize(d,a.apply)
    if a.action=='root-setup':return root_setup(d,a.apply)
    if a.action=='root':print(d.root(a.command));return
    if a.action=='backup':return backup(d)
    if a.action=='wifi-adb':
        require(a.apply,'启用无线ADB需要 --apply。');require(d.shell('getprop ro.adb.secure').strip()=='1','当前ADB认证状态异常，停止。')
        d.root('setprop persist.adb.tcp.port 5555')
        run(d.prefix+['tcpip','5555'])
        print('已请求启用认证无线ADB，连接会短暂中断。用设备Wi-Fi地址执行 adb connect IP:5555。');return
    if a.action=='build-rescue':
        from .images import build_rescue
        print(build_rescue(d,a.stock));return
    if a.action=='install-image':
        from .images import install
        print(json.dumps(install(d,a.kind,a.image,a.apply),ensure_ascii=False,indent=2));return
    if a.action=='rescue-check':
        require(a.from_fastboot,'必须本人实际从Preloader→FASTBOOT→救援进入后再加 --from-fastboot。')
        require(d.shell('getprop ro.xiaodu.rescue').strip()=='x1s-toolkit-v0.1.0','不是本工具的独立救援。')
        require(d.root('id').startswith('uid=0('),'救援root未确认。')
        installed=json.loads((d.work/'recovery-install-result.json').read_text())
        require(sha(d.read_block('recovery'))==installed['candidate_sha256'],'实际救援分区与安装记录不一致。')
        result={'binding':d.binding(),'independent_fastboot_entry_confirmed':True,'root_verified':True,'recovery_sha256':installed['candidate_sha256']};save(d.work/'rescue-verified.json',result);print('独立救援root与分区哈希核验通过。');return result
    if a.action=='bl-prepare':
        require(a.run_hacc,'临时内核执行需要明确 --run-hacc；先阅读 docs/04-bootloader.md。')
        from .unlock import prepare
        return prepare(d)
    if a.action=='bl-install':
        from .unlock import install
        return install(d,a.apply)
    if a.action=='verify':
        result=d.info()
        try:result['root_identity']=d.root('id').strip()
        except RuntimeError as e:result['root_error']=str(e)
        result['android_reports_unlocked']=result['ro.boot.flash.locked']=='0' and result['ro.boot.verifiedbootstate']=='orange'
        result['fastboot_confirmation']='请另用 fastboot getvar unlocked 核验，不能单凭Android属性认定。'
        save(d.work/'verify.json',result);print(json.dumps(result,ensure_ascii=False,indent=2));return result
