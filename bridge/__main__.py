"""Entry point: python3 -m bridge"""
import argparse
import os
import sys

# Ensure project root is on the path: bridge/ is at repo root
_bridge_pkg = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(_bridge_pkg)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from bridge.server import TeaPartyBridge

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

if not os.path.isdir(args.teaparty_home):
    parser.error(
        f'.teaparty/ not found: {args.teaparty_home}\n'
        'Run from a directory containing .teaparty/ or pass --teaparty-home <path>.'
    )

bridge = TeaPartyBridge(
    teaparty_home=args.teaparty_home,
    static_dir=os.path.join(project_root, 'bridge', 'static'),
)
print(f'Dashboard:  http://localhost:{args.port}')
bridge.run(port=args.port)
