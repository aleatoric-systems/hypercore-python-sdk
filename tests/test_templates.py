from __future__ import annotations

from hypercore_sdk.templates import render_nginx_grpc_template


def test_render_nginx_grpc_template_includes_expected_fields() -> None:
    rendered = render_nginx_grpc_template("hl.grpc.example.com", "127.0.0.1:50051")

    assert "server_name hl.grpc.example.com;" in rendered
    assert "grpc_pass grpc://127.0.0.1:50051;" in rendered
    assert "limit_req_zone $http_x_api_key" in rendered
