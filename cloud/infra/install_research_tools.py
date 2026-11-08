"""Install the pinned Claude CLI during an image build, never at worker startup."""
from pathlib import Path
import re
import shutil
import subprocess


def main():
    version = Path('/app/claude-code-version.txt').read_text().strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+', version): raise ValueError('Invalid Claude CLI pin')
    binary = shutil.which('claude')
    current = subprocess.run([binary, '--version'], capture_output=True, text=True, check=True).stdout if binary else ''
    if not current.startswith(version + ' '):
        subprocess.run(['npm', 'install', '--global', '--no-audit', '--no-fund', '@anthropic-ai/claude-code@' + version], check=True, timeout=180)
    result = subprocess.run(['claude', '--version'], capture_output=True, text=True, check=True).stdout
    if not result.startswith(version + ' '): raise RuntimeError('Claude CLI pin was not installed')
    missing = [package for binary, package in (('tesseract', 'tesseract-ocr'), ('rg', 'ripgrep')) if not shutil.which(binary)]
    if missing:
        subprocess.run(['apt-get', 'update'], check=True, timeout=120)
        subprocess.run(['apt-get', 'install', '-y', '--no-install-recommends', *missing], check=True, timeout=180)
        shutil.rmtree('/var/lib/apt/lists', ignore_errors=True)
    print('Pinned Claude Code CLI ready: ' + version)


if __name__ == '__main__': main()
