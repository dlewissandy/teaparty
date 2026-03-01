import subprocess, sys

task = open('/Users/darrell/git/teaparty/poc/projects/POC/.worktrees/session-20260301-063511/coding_task.txt').read()
result = subprocess.run(
    ['/Users/darrell/git/teaparty/poc/projects/POC/relay.sh', '--team', 'coding', '--task', task],
    capture_output=True, text=True, timeout=280
)
print('STDOUT:', result.stdout)
print('STDERR:', result.stderr)
print('RC:', result.returncode)
