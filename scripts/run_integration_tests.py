#!/usr/bin/env python3
"""Run integration tests."""

import subprocess
import sys

def main():
    result = subprocess.run(['pytest', 'tests/integration/', '-v'], cwd='..')
    sys.exit(result.returncode)

if __name__ == '__main__':
    main()
