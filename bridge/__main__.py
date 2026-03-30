"""Entry point: python3 -m bridge"""
import argparse
import os
import sys

# Ensure project root is on the path: bridge/ is at repo root
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
args = parser.parse_args()

bridge = TeaPartyBridge(
    teaparty_home=os.path.expanduser('~/.teaparty'),
    static_dir=os.path.join(project_root, 'docs', 'proposals', 'ui-redesign', 'mockup'),
)
print(f'Dashboard:  http://localhost:{args.port}')
bridge.run(port=args.port)
