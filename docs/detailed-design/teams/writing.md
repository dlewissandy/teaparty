# writing

Dispatch here when the task is to produce original written content from scratch. The team handles format and register — documentation, academic papers, blog posts, specifications — but expects the subject matter to be known or researched before dispatch. Do not send existing content here to be improved; that belongs to editorial.

---

## writing-lead

The writing-lead breaks the content brief into distinct artifacts or sections, assigns each to the appropriate writer, reviews drafts for coherence and completeness, stitches the pieces together, and delivers the final artifact. It requests clarification when the brief lacks format, audience, or scope definition, and declares completion when the artifact is whole, coherent, and matches the brief.

**Tools:** Read, Write, Edit, Glob, Grep, mcp__teaparty-config__AskQuestion
**Skills:** digest

---

## markdown-writer

Dispatch when the output is documentation, a README, a guide, or general prose in Markdown. The default choice for most project documentation. Not for LaTeX documents, blog posts with specific platform conventions, or formal specifications.

**Tools:** Read, Write, Edit, Glob, Grep
**Skills:** digest

---

## latex-writer

Dispatch when the output requires LaTeX — academic papers, technical reports with equations, or any document where typesetting precision matters. Not for general documentation or web-optimized content. Requires `pdflatex` or `tectonic` in the execution environment to compile and verify output.

**Tools:** Read, Write, Edit, Bash
**Skills:** digest

---

## blog-writer

Dispatch when the output is a blog post or other conversational, web-optimized content. Writes for general audiences with narrative flow and engagement in mind, not technical precision. Research and fact-checking are handled upstream; this agent writes from the brief it receives. Not for documentation or formal specifications.

**Tools:** Read, Write, Edit
**Skills:** digest

---

## pdf-writer

Dispatch when the output must be a PDF and the author does not need LaTeX — reports, proposals, formatted documents from Markdown or HTML source. Uses Pandoc or WeasyPrint to render; requires one of those to be installed in the execution environment. Not for documents requiring LaTeX-quality typesetting or equations (latex-writer).

**Tools:** Read, Write, Bash
**Skills:** digest

---

## specification-writer

Dispatch when the output is a formal specification, technical requirements document, or structured definition where every statement must be implementable. Works from intent or design artifacts; produces documents that execution teams can act on directly. Requests clarification when intent is ambiguous rather than assuming — a wrong spec is more expensive than a delayed one.

**Tools:** Read, Write, Edit, Glob, Grep, mcp__teaparty-config__AskQuestion
**Skills:** digest
