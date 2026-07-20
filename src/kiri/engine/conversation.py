from kiri.engine import agent
from kiri.tools.registry import build as build_registry


async def run_turn(session, text, store, mcp_tools, transport):
    # The single path both live DMs and scheduled jobs run through: assemble the
    # tools for this channel, then run the agent loop.
    registry = build_registry(store, session.channel_id, mcp_tools, transport)

    async def notify(message):
        await transport.send(session.channel_id, message)

    return await agent.run(session, text, registry, notify)
