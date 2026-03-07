import subprocess, pathlib, sys
task_file = pathlib.Path(__file__).parent.parent / '.relay_task.txt'
task = task_file.read_text()
relay = '/Users/darrell/git/teaparty/poc/projects/POC/relay.sh'
result = subprocess.run([relay, '--team', 'coding', '--task', task], text=True)
sys.exit(result.returncode)
