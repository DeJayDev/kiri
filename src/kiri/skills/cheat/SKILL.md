---
name: cheat
description: How to use a shell command, or how to do something in a language. Read this before answering such a question from memory -- it fetches a real, current example.
---

# cht.sh

Cheat sheets over plain curl, no install. Two forms.

Usage for one command (this is tldr-pages under the hood):

    curl -s 'https://cht.sh/tar?T'

A how-do-I question, scoped to a language -- this is the reason to reach
here instead of tldr, which only does bare commands:

    curl -s 'https://cht.sh/python/reverse+a+list?T'

Keep `?T` on every request. Without it the reply is wrapped in ANSI color
escapes that garbage the transcript and waste context. Spaces in a question
become `+` (`read+a+file+line+by+line`). The whole URL stays single-quoted so
the shell leaves `?` and `+` alone.

The answer form is a snippet from StackOverflow or cheat.sheets, not gospel --
read it, adapt it, don't paste it blind.
