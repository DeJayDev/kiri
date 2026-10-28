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
