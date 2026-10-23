#!/usr/bin/env python3
from xdtool.cli import main
if __name__=='__main__':
    try:main()
    except (RuntimeError,OSError,ValueError,KeyError) as exc:
        import sys
        print('停止：'+str(exc),file=sys.stderr)
        raise SystemExit(1)
