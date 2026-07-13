from kiri import mcp_client


def test_qualified_name_fits_the_provider_limit():
    name = mcp_client._qualify("a" * 80, "b" * 80)
    assert len(name) <= 64
