"""Exact-profile HACC calibration and per-device seccfg write; no bundled image."""
import json,re,secrets,shlex,struct,sys
from pathlib import Path
from .common import ROOT,require,run,save,sha
from .verify_avb1 import verify


def headers(old):
    require(len(old)==262144,'seccfg分区长度不匹配。')
    values=struct.unpack('<7I',old[:28])
    require(values[0]==0x4d4d4d4d and values[1:3]==(4,60) and values[6]==0x45454545,'不是已验证的seccfg V4布局。')
    require(values[3] in (1,3),'锁状态未知。')
    return values

def candidate(old,cipher):
    require(headers(old)[3]==1,'当前不是锁定状态，不生成写入镜像。')
    require(len(cipher)==32,'HACC校验长度错误。')
    new=bytearray(old);struct.pack_into('<I',new,12,3);new[28:60]=cipher
    require(new[:12]==old[:12] and new[16:28]==old[16:28] and new[60:]==old[60:],'变更超出锁字段及校验范围。')
    return bytes(new)

def prepare(d):
    require(__debug__,'不要使用python -O运行本工具。')
    p=json.loads((ROOT/'profiles/xdh29b1-1682.json').read_text())
    require(d.shell('getprop ro.build.display.id').strip()==p['firmware'],'BL工具仅适用于资料中核对过的1.68.2完整版本；不匹配就停止，不自动降级。')
    require(d.root('uname -r').strip()==p['kernel_release'] and d.root('uname -v').strip()==p['kernel_version'],'运行内核版本不匹配。')
    require(sha(d.read_block('lk'))==p['lk_sha256'] and sha(d.read_block('lk2'))==p['lk_sha256'],'LK/LK2不是已验证版本。')
    base=d.work/'bl';base.mkdir(mode=0o700,exist_ok=False)
    old=d.read_block('seccfg');values=headers(old)
    require(values[3]==1,'当前已解锁；不要重复写入。')
    boot=base/'current-boot.img';boot.write_bytes(d.read_block('boot'))
    require(verify(boot,'/boot')['kernel_sha256']==p['boot_kernel_sha256'],'当前boot内核不匹配。')
    donor=d.root('cat /vendor/lib/modules/wmt_chrdev_wifi.ko',binary=True)
    require(sha(donor)==p['donor_sha256'],'原厂模块ABI模板不匹配。')
    (base/'donor.ko').write_bytes(donor)
    # Resolve symbols in the current kernel and restore the exact prior kptr value.
    symbols=d.root('''set -e
old=$(cat /proc/sys/kernel/kptr_restrict)
trap 'echo "$old" > /proc/sys/kernel/kptr_restrict' EXIT HUP INT TERM
echo 0 > /proc/sys/kernel/kptr_restrict
cat /proc/kallsyms | grep -E ' (printk|masp_hal_sp_hacc_enc|masp_hal_sp_hacc_dec)$'
''')
    for name,address in p['functions'].items():
        match=re.search(r'^([0-9a-f]+) [A-Za-z] '+re.escape(name)+r'$',symbols,re.M)
        require(match and int(match[1],16)==address,'当前内核函数地址不匹配：'+name)
    newhead=bytearray(old[:28]);struct.pack_into('<I',newhead,12,3)
    nonce=secrets.token_hex(4);prefix='x1shacc_'+nonce
    asm='''.syntax unified
.arm
.text
.global probe_init
probe_init:
 push {r4-r8, lr}
 sub sp, sp, #48
 adr r0, old_cipher
 add r1, sp, #8
 bl copy32
 ldr r8, =DEC
 bl hacc
 mov r1, #0
 bl output
 ldr r8, =ENC
 bl hacc
 mov r1, #1
 bl output
 adr r0, new_hash
 add r1, sp, #8
 bl copy32
 ldr r8, =ENC
 bl hacc
 mov r1, #2
 bl output
 ldr r8, =DEC
 bl hacc
 mov r1, #3
 bl output
 add sp, sp, #48
 mov r0, #0
 pop {r4-r8, pc}
copy32:
 ldmia r0!, {r2-r5}
 stmia r1!, {r2-r5}
 ldmia r0, {r2-r5}
 stmia r1, {r2-r5}
 bx lr
hacc:
 add r0, sp, #8
 mov r1, #32
 mov r2, #1
 mov r3, #0
 mov r4, #1
 str r4, [sp]
 bx r8
output:
 adr r0, probe_format
 mov r2, #32
 add r3, sp, #8
 ldr r8, =PRINTK
 bx r8
 .align 2
old_cipher:
 .byte OLD
new_hash:
 .byte NEW
probe_format:
 .asciz "<6>PREFIX:%u:%*phN\\n"
 .align 2
 .ltorg
'''.replace('DEC',hex(p['functions']['masp_hal_sp_hacc_dec'])).replace('ENC',hex(p['functions']['masp_hal_sp_hacc_enc'])).replace('PRINTK',hex(p['functions']['printk'])).replace('OLD',','.join(hex(x) for x in old[28:60])).replace('NEW',','.join(hex(x) for x in bytes.fromhex(sha(newhead)))).replace('PREFIX',prefix)
    (base/'hacc.S').write_text(asm)
    run(['arm-linux-gnueabi-as','-march=armv7-a','-o',base/'hacc.o',base/'hacc.S'])
    run(['arm-linux-gnueabi-objcopy','-O','binary','-j','.text',base/'hacc.o',base/'hacc.bin'])
    name='xiaodu_probe_'+nonce
    run([sys.executable,ROOT/'xdtool/build_kernel_probe.py','--donor',base/'donor.ko','--out',base/'hacc.ko','--name',name,'--payload',base/'hacc.bin'])
    remote='/dev/'+name+'.ko'
    d.root('cat > '+remote+' && chmod 600 '+remote,data=(base/'hacc.ko').read_bytes())
    try:
        output=d.root('set -e; insmod '+remote+'; rmmod '+name+'; dmesg | grep '+prefix+':')
    finally:
        # Best-effort unload even if the proof read failed; no persistent module is installed.
        d.root('rmmod '+name+' 2>/dev/null || :; rm -f '+remote)
    found={int(k):bytes.fromhex(v) for k,v in re.findall(re.escape(prefix)+r':([0-3]):([0-9a-f]{64})',output)}
    require(set(found)=={0,1,2,3},'HACC回验结果不完整；没有写分区。')
    require(found[0].hex()==sha(old[:28]) and found[1]==old[28:60] and found[3].hex()==sha(newhead),'HACC回验不匹配；没有写分区。')
    new=candidate(old,found[2])
    (base/'before.img').write_bytes(old);(base/'candidate.img').write_bytes(new)
    proof={'binding':d.binding(),'profile':p['firmware'],'before_sha256':sha(old),'candidate_sha256':sha(new),'hacc_roundtrip_verified':True,'before_header_sha256':sha(old[:28]),'candidate_header_sha256':sha(new[:28]),'ciphertext':found[2].hex(),'changed_offsets':[i for i,(x,y) in enumerate(zip(old,new)) if x!=y],'storage_written':False,'module_unloaded':True}
    save(base/'plan.json',proof)
    print('已完成HACC四项回验，临时模块已卸载。尚未写seccfg。计划：',base/'plan.json')
    return proof

def install(d,apply=False):
    require(apply,'实际写入需要 --apply；先阅读 docs/04-bootloader.md。')
    base=d.work/'bl';plan=json.loads((base/'plan.json').read_text())
    old=(base/'before.img').read_bytes();new=(base/'candidate.img').read_bytes()
    require(plan['binding']==d.binding(),'写入计划不属于当前机器。')
    require(plan['hacc_roundtrip_verified'] is True and sha(old)==plan['before_sha256'] and sha(new)==plan['candidate_sha256'],'计划或本地文件不匹配。')
    require(candidate(old,bytes.fromhex(plan['ciphertext']))==new,'候选变更范围错误。')
    profile=json.loads((ROOT/'profiles/xdh29b1-1682.json').read_text())
    require(sha(d.read_block('lk'))==profile['lk_sha256'] and sha(d.read_block('lk2'))==profile['lk_sha256'],'生成计划后LK/LK2已变化，拒绝写入。')
    require(d.read_block('seccfg')==old,'当前seccfg已变化；拒绝写入。')
    partition=d.block('seccfg');stage='/dev/x1s-seccfg-'+secrets.token_hex(4)
    d.root('cat > '+stage+' && chmod 600 '+stage,data=old[:512]+new[:512])
    command=f'''set -eu
bb=/data/adb/magisk/busybox
[ -x "$bb" ]
trap 'rm -f {stage} {stage}.old {stage}.new' EXIT HUP INT TERM
[ "$(getprop ro.build.display.id)" = {shlex.quote(plan['profile'])} ]
[ "$($bb blockdev --getsize64 {partition})" = 262144 ]
[ "$($bb sha256sum {partition} | $bb cut -d ' ' -f 1)" = {sha(old)} ]
$bb dd if={stage} of={stage}.old bs=512 count=1 2>/dev/null
$bb dd if={stage} of={stage}.new bs=512 skip=1 count=1 2>/dev/null
[ "$($bb sha256sum {stage}.new | $bb cut -d ' ' -f 1)" = {sha(new[:512])} ]
rc=0
$bb dd if={stage}.new of={partition} bs=512 count=1 conv=notrunc 2>/dev/null || rc=$?
sync
actual=$($bb sha256sum {partition} | $bb cut -d ' ' -f 1)
if [ "$rc" != 0 ] || [ "$actual" != {sha(new)} ]; then
 $bb dd if={stage}.old of={partition} bs=512 count=1 conv=notrunc 2>/dev/null
 sync
 echo ROLLED_BACK >&2
 exit 31
fi
echo SECCFG_WRITE_VERIFIED
'''
    output=d.root(command)
    require(d.read_block('seccfg')==new,'主机回读未匹配；停止，不自动重启。')
    result={'readback_verified':True,'before_sha256':sha(old),'candidate_sha256':sha(new),'bytes_written':512,'rebooted':False,'actual_unlock':'pending fastboot verification','output':output}
    save(base/'install-result.json',result)
    print('首扇区写入与回读通过。还需冷启动进入Fastboot核验，不会自动重启。')
    return result
