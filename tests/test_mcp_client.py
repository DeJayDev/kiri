from kiri import mcp_client


def test_qualified_name_fits_the_provider_limit():
    name = mcp_client._qualify("a" * 80, "b" * 80)
    assert len(name) <= 64


def test_an_image_result_becomes_an_image_block_beside_the_text():
    from mcp.types import CallToolResult, ImageContent, TextContent

    result = CallToolResult(
        content=[TextContent(type="text", text="screenshot"), ImageContent(type="image", data="AAA", mimeType="image/png")]
    )
    assert mcp_client._flatten(result) == [
        {"type": "text", "text": "screenshot"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAA"}},
    ]


def test_a_text_only_result_stays_a_capped_string():
    from mcp.types import CallToolResult, TextContent

    result = CallToolResult(content=[TextContent(type="text", text="x" * 40000)])
    out = mcp_client._flatten(result)
    assert isinstance(out, str)
    assert "...[truncated]..." in out


def test_an_image_the_model_cannot_view_is_left_out_with_a_note():
    from mcp.types import CallToolResult, ImageContent

    result = CallToolResult(content=[ImageContent(type="image", data="AAA", mimeType="image/heic")])

    assert mcp_client._flatten(result) == "[a image/heic image was left out: not a type or size you can view]"


def test_a_server_that_fails_to_start_is_reported_instead_of_crashing_boot(tmp_path):
    import asyncio
    import json
    from contextlib import AsyncExitStack

    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"servers": {"broken": {"command": "kiri-no-such-binary"}}}))

    async def go():
        async with AsyncExitStack() as stack:
            return await mcp_client.load(str(path), stack)

    tools, [(name, reason)] = asyncio.run(go())
    assert tools == []
    assert name == "broken"
    assert reason.startswith("FileNotFoundError")
