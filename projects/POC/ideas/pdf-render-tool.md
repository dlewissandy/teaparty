# Idea: PDF render tool for LaTeX documents

## Problem

Agents editing LaTeX documents need to compile them to verify their changes build cleanly. Currently this requires Bash access to run `pdflatex` and `bibtex`, but:

1. The sandbox blocks `pdflatex` by default.
2. Granting full Bash access to work around this is overly broad.
3. The compile pipeline (`pdflatex` → `bibtex` → `pdflatex` → `pdflatex`) is a fixed sequence that doesn't benefit from agent autonomy — it's mechanical, not creative.

## Desired behaviour

A dedicated tool (e.g., `RenderPdf`) that an agent can call with a `.tex` file path. The tool handles the full `pdflatex` + `bibtex` build pipeline internally and returns success/failure with any error output. The agent never needs Bash access or knowledge of the compile sequence.

## What it is not

- Not a general-purpose Bash escape hatch.
- Not a preview/viewer — it produces the PDF artifact on disk. Viewing is the human's concern.
