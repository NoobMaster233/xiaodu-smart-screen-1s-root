import struct,unittest
from xdtool.unlock import headers,candidate

class LockGuards(unittest.TestCase):
    def setUp(self):
        self.old=bytearray(b'\x5a'*262144)
        self.old[:28]=struct.pack('<7I',0x4d4d4d4d,4,60,1,1,0,0x45454545)
    def test_only_lock_and_authenticator_can_change(self):
        cipher=bytes(range(32));new=candidate(bytes(self.old),cipher)
        changed={i for i,(a,b) in enumerate(zip(self.old,new)) if a!=b}
        self.assertTrue(changed<={12,13,14,15,*range(28,60)})
        self.assertEqual(new[512:],self.old[512:]);self.assertEqual(headers(new)[3],3)
    def test_wrong_partition_length_refused(self):
        with self.assertRaises(RuntimeError):headers(self.old[:-1])
    def test_wrong_format_refused(self):
        self.old[4:8]=struct.pack('<I',3)
        with self.assertRaises(RuntimeError):headers(self.old)
    def test_unknown_lock_refused(self):
        struct.pack_into('<I',self.old,12,2)
        with self.assertRaises(RuntimeError):headers(self.old)
    def test_already_unlocked_refused(self):
        struct.pack_into('<I',self.old,12,3)
        with self.assertRaises(RuntimeError):candidate(self.old,bytes(32))
    def test_invalid_authenticator_refused(self):
        with self.assertRaises(RuntimeError):candidate(self.old,bytes(31))

class NoImplicitWrite(unittest.TestCase):
    def test_bl_install_without_apply_does_not_touch_device(self):
        from xdtool.unlock import install
        class DeviceTrap:
            def __getattr__(self,name):raise AssertionError('device used: '+name)
        with self.assertRaises(RuntimeError):install(DeviceTrap(),False)
    def test_image_install_without_apply_does_not_touch_device(self):
        from xdtool.images import install
        class DeviceTrap:
            def __getattr__(self,name):raise AssertionError('device used: '+name)
        with self.assertRaises(RuntimeError):install(DeviceTrap(),'boot','missing.img',False)


class RootTransportGuards(unittest.TestCase):
    def test_su_command_is_one_quoted_argument(self):
        import shlex
        from xdtool.common import Device
        class Capture(Device):
            def __init__(self):self._root='su';self.command=None
            def shell(self,command,data=None,binary=False):self.command=command;return ''
        d=Capture();script='printf "%s\\n" "a b"\nprintf "%s" "$(printf test)"'
        d.root(script)
        self.assertEqual(shlex.split(d.command),['/sbin/su','-c',script])

    def test_bdft_binary_stdin_covers_whole_compound_command(self):
        import tempfile,subprocess,shlex
        from pathlib import Path
        from xdtool.common import Device
        remote='/data/local/tmp/x1s-toolkit'
        with tempfile.TemporaryDirectory(prefix='x1s-stdin-test-') as tmp:
            folder=Path(tmp)
            class Simulated(Device):
                def __init__(self):self.work=folder;self._root='bdft';self.request=b'';self.payload=b'';self.output=b'';self.code=0
                def shell(self,command,data=None,binary=False):
                    if command.startswith('stat -c'):return '0:2000:640\n'
                    if command.startswith('busybox lsattr'):return '----i------- /data/log/FactoryConfig\n'
                    if 'cat > '+remote+'/input.bin' in command:self.payload=data;return ''
                    if 'cat > '+remote+'/request.sh' in command:self.request=data;return ''
                    if command=='getprop init.svc.bdft_server':return 'running\n'
                    if command=='bdft audio -play /dev/null':
                        (folder/'input.bin').write_bytes(self.payload)
                        result=subprocess.run(['bash','-c',self.request.decode().replace(remote,str(folder))],capture_output=True)
                        self.code=result.returncode;self.output=result.stdout;return ''
                    if command=='cat '+remote+'/exitcode':return str(self.code)
                    if command=='cat '+remote+'/stdout':return self.output
                    if command=='cat '+remote+'/stderr':return ''
                    if command.startswith(('rm -f ','setprop ctl.start ')):return ''
                    raise AssertionError(command)
            d=Simulated();target=folder/'binary output';data=b'\x00\xffhello\n'
            d.root('cat > '+shlex.quote(str(target))+' && chmod 600 '+shlex.quote(str(target)),data=data)
            self.assertEqual(target.read_bytes(),data)

if __name__=='__main__':unittest.main()
