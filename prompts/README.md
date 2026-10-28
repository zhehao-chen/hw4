# prompts/

Every prompt you write lives here, one file each, and your code loads it with
`ctx.prompt("name.md")`. Nothing else in the repository holds prompt text.

This matters for the seven-layer audit in `ARCHITECTURE.md`: a layer whose only
enforcement is a file in `prompts/` is **EMPTY**, because a sentence in a prompt
is a request to the model, not a control.
