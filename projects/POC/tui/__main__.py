"""Entry point: python3 -m projects.POC.tui"""
import argparse
import os
import sys

# Ensure project root is on the path so we can import stream._common etc.
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Also add POC root so `from stream._common import ...` works
poc_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if poc_root not in sys.path:
    sys.path.insert(0, poc_root)

from projects.POC.tui.app import TeaPartyTUI

parser = argparse.ArgumentParser(description='TeaParty TUI')
parser.add_argument(
    '--project-dir',
    type=str,
    default=None,
    metavar='DIR',
    help='Directory containing project folders (default: auto-discovered teaparty projects/)',
)
args = parser.parse_args()

projects_dir = None
if args.project_dir:
    projects_dir = os.path.realpath(os.path.abspath(args.project_dir))

app = TeaPartyTUI(projects_dir=projects_dir)
app.run()
