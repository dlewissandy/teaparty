"""Entry point: python3 -m teaparty.bridge"""
import argparse
import logging
import os
import sys

# Ensure repo root is on the path (teaparty/ is a sub-package of repo root)
_bridge_pkg = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(_bridge_pkg))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from teaparty.bridge.server import TeaPartyBridge

parser = argparse.ArgumentParser(description='TeaParty bridge server (HTML dashboard)')
parser.add_argument(
    '--port',
    type=int,
    default=8081,
    metavar='PORT',
    help='Port to listen on (default: 8081)',
)
parser.add_argument(
    '--teaparty-home',
    default=os.path.join(os.getcwd(), '.teaparty'),
    metavar='DIR',
    help='Path to .teaparty/ config directory (default: <cwd>/.teaparty)',
)
args = parser.parse_args()

log_fmt = '%(asctime)s %(name)s %(levelname)s %(message)s'
logging.basicConfig(level=logging.DEBUG, format=log_fmt, stream=sys.stderr)

# Persist teaparty logs to .teaparty/logs/bridge.log so dispatch
# activity (spawn, reply, reinvoke) is inspectable after the fact.
log_dir = os.path.join(args.teaparty_home, 'logs')
os.makedirs(log_dir, exist_ok=True)
_fh = logging.FileHandler(os.path.join(log_dir, 'bridge.log'))
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(logging.Formatter(log_fmt))
logging.getLogger('teaparty').addHandler(_fh)

if not os.path.isdir(args.teaparty_home):
    parser.error(
        f'.teaparty/ not found: {args.teaparty_home}\n'
        'Run from a directory containing .teaparty/ or pass --teaparty-home <path>.'
    )

bridge = TeaPartyBridge(
    teaparty_home=args.teaparty_home,
    static_dir=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static'),
)
print(f'Dashboard:  http://localhost:{args.port}')
bridge.run(port=args.port)
