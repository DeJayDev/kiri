SCHEMA = {
    "name": "ask",
    "description": (
        "Ask the owner a question and wait for the answer. Use it when the choice "
        "is the owner's to make; write the likely answers as options so the owner "
        "picks instead of typing, and they can always answer something else."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "What you need to know, in one sentence.",
            },
            "options": {
                "type": "array",
                "description": "The answers you think are likely, for the owner to pick from.",
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {
                            "type": "string",
                            "description": "The answer itself, kept short.",
                        },
                        "description": {
                            "type": "string",
                            "description": "What picking it means, when the label alone is thin.",
                        },
                    },
                    "required": ["label"],
                },
            },
            "multi_select": {
                "type": "boolean",
                "description": "True when the options are not mutually exclusive.",
            },
        },
        "required": ["question", "options"],
    },
}


def build(transport, channel_id):
    async def ask(args):
        options = args["options"]
        if not options:
            return "error: ask needs at least one option; with none, put the question in your reply"
        if len(options) > 5:
            return f"error: ask takes at most 5 options, not {len(options)}; narrow the question"
        answer = await transport.ask(
            channel_id,
            args["question"],
            options,
            bool(args.get("multi_select")),
        )
        return answer or "error: the owner gave no answer"

    return ask
