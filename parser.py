import json
import socket
import sys
from urllib.parse import urlparse, parse_qs, unquote
import requests

# =====================================================================
# ВСТАВЬТЕ СЮДА ВАШУ ССЫЛКУ С ГИТХАБА (ГДЕ ЛЕЖАТ СТРОКИ vless://)
SUBSCRIBE_URL = "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/Vless-Reality-White-Lists-Rus-Mobile.txt"
# =====================================================================

def fetch_links(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        lines = [line.strip() for line in response.text.splitlines() if line.strip()]
        return lines
    except Exception as e:
        print(f"Ошибка при скачивании списка серверов: {e}")
        sys.exit(1)

def parse_vless_link(link):
    if isinstance(link, list):
        link = str(link[0]) if link else ""
    else:
        link = str(link)

    if not link.startswith("vless://"):
        return None
    try:
        main_part, *name_part = link.split('#')
        name = unquote(name_part) if name_part else "Без названия"
        
        parsed = urlparse(main_part)
        uuid = parsed.username
        hostname = parsed.hostname
        
        try:
            ip = socket.gethostbyname(hostname)
        except Exception:
            ip = hostname
            
        port = parsed.port
        queries = parse_qs(parsed.query)
        
        def get_param(key, default=""):
            val = queries.get(key, [default])
            return str(val[0]) if val else default

        net_type = get_param("type", "tcp")
        if net_type == "raw" or not net_type:
            net_type = "tcp"
            
        return {
            "ip": ip,
            "port": int(port),
            "id": uuid,
            "network": net_type,
            "security": get_param("security", "none"),
            "sni": get_param("sni"),
            "pbk": get_param("pbk"),
            "sid": get_param("sid"),
            "path": get_param("path", "/"),
            "serviceName": get_param("serviceName"),
            "host": get_param("host"),
            "name": name
        }
    except Exception as e:
        return None

def check_server_port(ip, port, timeout=2):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except Exception:
        return False

def build_xray_chain(ru_node, foreign_node):
    # Настройки стрима для Зарубежного сервера
    foreign_stream = {
        "network": foreign_node["network"],
        "security": foreign_node["security"]
    }
    
    if foreign_node["security"] == "reality":
        foreign_stream["realitySettings"] = {
            "show": False,
            "fingerprint": "firefox",
            "serverName": foreign_node["sni"],
            "publicKey": foreign_node["pbk"],
            "shortId": foreign_node["sid"],
            "spiderX": "/"
        }
    elif foreign_node["security"] == "tls":
        foreign_stream["tlsSettings"] = {
            "serverName": foreign_node["sni"] if foreign_node["sni"] else foreign_node["host"],
            "allowInsecure": False
        }

    if foreign_node["network"] == "grpc":
        foreign_stream["grpcSettings"] = {
            "serviceName": foreign_node["serviceName"] if foreign_node["serviceName"] else "grpc-direct"
        }
    elif foreign_node["network"] == "ws":
        foreign_stream["wsSettings"] = {
            "path": foreign_node["path"],
            "headers": {"Host": foreign_node["host"] if foreign_node["host"] else foreign_node["sni"]}
        }

    # Настройки стрима для Российского сервера
    ru_stream = {
        "network": ru_node["network"],
        "security": ru_node["security"]
    }
    
    if ru_node["security"] == "reality":
        ru_stream["realitySettings"] = {
            "show": False,
            "fingerprint": "firefox",
            "serverName": ru_node["sni"],
            "publicKey": ru_node["pbk"],
            "shortId": ru_node["sid"],
            "spiderX": "/"
        }
    elif ru_node["security"] == "tls":
        ru_stream["tlsSettings"] = {
            "serverName": ru_node["sni"] if ru_node["sni"] else ru_node["host"],
            "allowInsecure": False
        }

    if ru_node["network"] == "ws":
        ru_stream["wsSettings"] = {
            "path": ru_node["path"],
            "headers": {"Host": ru_node["host"] if ru_node["host"] else ru_node["sni"]}
        }
    elif ru_node["network"] == "grpc":
        ru_stream["grpcSettings"] = {
            "serviceName": ru_node["serviceName"] if ru_node["serviceName"] else "grpc-direct"
        }

    config = {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "port": 10808,
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": True}
            },
            {
                "port": 10809,  # Отдельный порт под мост для RU трафика
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": True}
            }
        ],
        "routing": {
            "domainStrategy": "AsIs",
            "rules": [
                {
                    "type": "field",
                    "inboundTag": ["socks"],
                    "outboundTag": "server2-final"
                }
            ]
        },
        "outbounds": [
            {
                "tag": "server2-final",
                "protocol": "vless",
                "settings": {
                    "vnext": [{
                        "address": foreign_node["ip"],
                        "port": foreign_node["port"],
                        "users": [{
                            "id": foreign_node["id"],
                            "encryption": "none"
                        }]
                    }]
                },
                "streamSettings": foreign_stream,
                # Перенаправляем трафик в локальный порт первого сервера
                "proxySettings": {
                    "tag": "server1-relay"
                }
            },
            {
                "tag": "server1-relay",
                "protocol": "vless",
                "settings": {
                    "vnext": [{
                        "address": ru_node["ip"],
                        "port": ru_node["port"],
                        "users": [{
                            "id": ru_node["id"],
                            "encryption": "none"
                        }]
                    }]
                },
                "streamSettings": ru_stream
            }
        ]
    }
    return config

def main():
    raw_links = fetch_links(SUBSCRIBE_URL)
    ru_pool = []
    foreign_pool = []
    
    for link in raw_links:
        node = parse_vless_link(link)
        if not node:
            continue
        name_lower = node["name"].lower()
        if "russia" in name_lower or "россия" in name_lower or "ru" in name_lower or "🇷🇺" in node["name"]:
            ru_pool.append(node)
        else:
            foreign_pool.append(node)
            
    active_ru = None
    active_foreign = None
    
    for node in ru_pool:
        if check_server_port(node["ip"], node["port"]):
            active_ru = node
            break
            
    for node in foreign_pool:
        if check_server_port(node["ip"], node["port"]):
            active_foreign = node
            break
            
    if not active_ru or not active_foreign:
        sys.exit(1)
        
    final_json = build_xray_chain(active_ru, active_foreign)
    
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(final_json, f, indent=4, ensure_ascii=False)

if __name__ == "__main__":
    main()
