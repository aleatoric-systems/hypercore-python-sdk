from __future__ import annotations


def render_nginx_grpc_template(server_name: str, upstream: str) -> str:
    return f"""# /etc/nginx/conf.d/hypercore-grpc.conf
limit_req_zone $http_x_api_key zone=hft_limit:10m rate=5000r/s;

map $http_x_api_key $client_id {{
    default "";
    # "replace-with-real-key" "trader_1";
}}

server {{
    listen 443 ssl http2;
    server_name {server_name};

    ssl_certificate /etc/letsencrypt/live/{server_name}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{server_name}/privkey.pem;

    if ($client_id = "") {{
        return 403;
    }}

    location / {{
        limit_req zone=hft_limit burst=1000 nodelay;
        grpc_pass grpc://{upstream};
        grpc_socket_keepalive on;
        grpc_read_timeout 1h;
        grpc_send_timeout 1h;
    }}
}}
"""
