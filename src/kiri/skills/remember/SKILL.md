---
name: remember
description: Read this before saving a durable fact to long-term memory or recalling one, so a note lands where later greps find it and nothing overwrites what is already there.
---

# remember

Long-term memory is flat files. Your environment note gives the absolute
directory path; use it literally below in place of <mem>. Do not write
`$MEMORY_DIR` -- that variable is not set in the shell and expands to nothing,
so the note lands in the wrong place.

Recall first, always, before you write or before you claim you don't know:

    rg -i '<topic>' <mem>

Then save, one fact per line, appended:

    printf '%s\n' '<the fact>' >> <mem>/notes.md

Use `>>`, never `>`. A single `>` truncates the file and erases every note in
it. Use `printf '%s\n'`, never `echo`: a fact that starts with `-` or contains
a backslash comes out mangled or swallowed under echo.

Recall before writing is not optional -- it is how you avoid saving the same
fact twice under slightly different words. If rg already returns it, don't
append it again.
