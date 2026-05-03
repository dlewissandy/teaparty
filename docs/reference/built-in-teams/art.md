# art

Dispatch here when the task requires a visual artifact — a diagram, illustration, figure, or generated image. The team produces visual output, not written content or data charts. If the format matters (SVG, Graphviz, TikZ, PNG), specify it; otherwise let the lead choose the right medium for the content.

---

## art-lead

The art-lead interprets the visual brief, decides which format and artist is appropriate for the content, dispatches work, reviews output for accuracy and clarity, and delivers the final artifact. It requests clarification when the intended audience, medium, or content is undefined, and declares completion when the artifact communicates its content accurately in the chosen format.

**Tools:** [standard workgroup-lead tools](index.md#standard-workgroup-lead-tools)
**Skills:** digest

---

## svg-artist

Dispatch when the output is a vector illustration, icon, or structured diagram requiring precise control over visual elements. SVG is resolution-independent and suitable for web, documentation, and print. Not for graph-based diagrams (graphviz-artist) or technical mathematical figures (tikz-artist).

**Tools:** Write, Read
**Skills:** digest

---

## graphviz-artist

Dispatch when the output is a node-edge diagram — dependency graphs, flowcharts, architecture diagrams, or any structure that can be expressed as a directed or undirected graph. Writes DOT language and uses Bash to render it via the `dot` command. Not for freeform illustrations or mathematical figures.

**Tools:** Write, Read, Bash
**Skills:** digest

---

## tikz-artist

Dispatch when the output requires precise technical or mathematical figures — diagrams for academic papers, circuit diagrams, geometric constructions, or any content where LaTeX-quality typesetting is expected. Not for general illustrations or graph diagrams. Requires `pdflatex` or `tectonic` in the execution environment to compile and verify output.

**Tools:** Write, Read, Bash
**Skills:** digest

---

## png-artist

Dispatch when the output is a raster image that requires generative AI — photorealistic scenes, stylized illustrations, or any visual that cannot be expressed as structured markup. Specify subject, style, and dimensions in the brief.

**Tools:** Write, mcp__teaparty-config__image_gen_openai, mcp__teaparty-config__image_gen_flux, mcp__teaparty-config__image_gen_stability
**Skills:** digest
