"""Entry point: python3 -m projects.POC.bridge"""
import argparse
import os
import sys

# Ensure project root is on the path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from projects.POC.bridge.server import TeaPartyBridge

parser = argparse.ArgumentParser(description='TeaParty bridge server (HTML dashboard)')
parser.add_argument(
    '--port',
    type=int,
    default=8081,
    metavar='PORT',
    help='Port to listen on (default: 8081)',
)
parser.add_argument(
    '--project-dir',
    type=str,
    default=None,
    metavar='DIR',
    help='Directory containing project folders (default: auto-discovered)',
)
args = parser.parse_args()

projects_dir = None
if args.project_dir:
    projects_dir = os.path.realpath(os.path.abspath(args.project_dir))
else:
    # Auto-discover: look for a projects/ sibling of the teaparty home
    teaparty_home = os.path.expanduser('~/.teaparty')
    candidate = os.path.join(os.path.dirname(teaparty_home), 'projects')
    if os.path.isdir(candidate):
        projects_dir = candidate

bridge = TeaPartyBridge(
    teaparty_home=os.path.expanduser('~/.teaparty'),
    projects_dir=projects_dir or '',
    static_dir=os.path.join(project_root, 'docs', 'proposals', 'ui-redesign', 'mockup'),
)
bridge.run(port=args.port)
