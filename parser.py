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
        return response.text.strip().splitlines()
    except Exception as e:
        print(f"Ошибка при скачивании списка серверов: {e}")
        sys.exit(1)

def parse_vless_link(link):
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
            return val[0] if val else default

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
        print(f"Не удалось распарсить ссылку... Ошибка: {e}")
        return None

def check_server_port(ip, port, timeout=2):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except Exception:
        return False

def build_singbox_chain(ru_node, foreign_node):
    """Строит ванильный и 100% рабочий Sing-box JSON для утилиты Happ"""
    
    # Сборка финального зарубежного аутбаунда
    foreign_outbound = {
        "type": "vless",
        "tag": "foreign-final",
        "server": foreign_node["ip"],
        "server_port": foreign_node["port"],
        "uuid": foreign_node["id"],
        "flow": "",
        "packet_encoding": "xray",
        "detour": "ru-relay"  # Направляем этот профиль ЧЕРЕЗ РУ узел
    }
    
    # Добавляем TLS / Reality зарубежному серверу
    if foreign_node["security"] == "reality":
        foreign_outbound["tls"] = {
            "enabled": True,
            "server_name": foreign_node["sni"],
            "utls": {"enabled": True, "fingerprint": "firefox"},
            "reality": {
                "enabled": True,
                "public_key": foreign_node["pbk"],
                "short_id": foreign_node["sid"]
            }
        }
    elif foreign_node["security"] == "tls":
        foreign_outbound["tls"] = {
            "enabled": True,
            "server_name": foreign_node["sni"] if foreign_node["sni"] else foreign_node["host"],
            "insecure": False,
            "utls": {"enabled": True, "fingerprint": "firefox"}
        }

    # Транспорт зарубежного сервера
    if foreign_node["network"] == "ws":
        foreign_outbound["transport"] = {
            "type": "ws",
            "path": foreign_node["path"],
            "headers": {"Host": foreign_node["host"] if foreign_node["host"] else foreign_node["sni"]}
        }
    elif foreign_node["network"] == "grpc":
        foreign_outbound["transport"] = {
            "type": "grpc",
            "service_name": foreign_node["serviceName"] if foreign_node["serviceName"] else "grpc-direct"
        }

    # Сборка промежуточного российского аутбаунда
    ru_outbound = {
        "type": "vless",
        "tag": "ru-relay",
        "server": ru_node["ip"],
        "server_port": ru_node["port"],
        "uuid": ru_node["id"],
        "flow": "",
        "packet_encoding": "xray"
    }

    # Добавляем TLS / Reality российскому серверу
    if ru_node["security"] == "reality":
        ru_outbound["tls"] = {
            "enabled": True,
            "server_name": ru_node["sni"],
            "utls": {"enabled": True, "fingerprint": "firefox"},
            "reality": {
                "enabled": True,
                "public_key": ru_node["pbk"],
                "short_id": ru_node["sid"]
            }
        }
    elif ru_node["security"] == "tls":
        ru_outbound["tls"] = {
            "enabled": True,
            "server_name": ru_node["sni"] if ru_node["sni"] else ru_node["host"],
            "insecure": False,
            "utls": {"enabled": True, "fingerprint": "firefox"}
        }

    # Транспорт российского сервера
    if ru_node["network"] == "ws":
        ru_outbound["transport"] = {
            "type": "ws",
            "path": ru_node["path"],
            "headers": {"Host": ru_node["host"] if ru_node["host"] else ru_node["sni"]}
        }
    elif ru_node["network"] == "grpc":
        ru_outbound["transport"] = {
            "type": "grpc",
            "service_name": ru_node["serviceName"] if ru_node["serviceName"] else "grpc-direct"
        }

    # Финальный конфиг Sing-box
    config = {
        "log": {"level": "warn"},
        "inbounds": [
            {
                "type": "socks",
                "tag": "socks-in",
                "listen": "127.0.0.1",
                "listen_port": 10808,
                "sniff": True,
                "udp_fragment": True
            }
        ],
        "outbounds": [
            foreign_outbound,
            ru_outbound,
            {"type": "direct", "tag": "direct"}
        ],
        "route": {
            "rules": [
                {"network": ["tcp", "udp"], "outbound": "foreign-final"}
            ]
        }
    }
    return config

def main():
    print("1. Загрузка списка серверов...")
    raw_links = fetch_links(SUBSCRIBE_URL)
    
    ru_pool, foreign_pool = [], []
    
    print("\n2. Сортировка по имени...")
    for link in raw_links:
        node = parse_vless_link(link)
        if not node:
            continue
            
        name_lower = node["name"].lower()
        if "russia" in name_lower or "россия" in name_lower or "ru" in name_lower or "🇷🇺" in node["name"]:
            ru_pool.append(node)
        else:
            foreign_pool.append(node)
            
    active_ru, active_foreign = None, None
    
    print("\n3. Тест портов...")
    for node in ru_pool:
        if check_server_port(node["ip"], node["port"]):
            active_ru = node
            break
            
    for node in foreign_pool:
        if check_server_port(node["ip"], node["port"]):
            active_foreign = node
            break
            
    if not active_ru or not active_foreign:
        print("[ОШИБКА] Не удалось собрать рабочую пару.")
        sys.exit(1)
        
    print(f"Сборка Sing-box цепи: Вы -> {active_ru['ip']} -> {active_foreign['ip']}")
    final_json = build_singbox_chain(active_ru, active_foreign)
    
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(final_json, f, indent=4, ensure_ascii=False)
        
    print("[ГОТОВО] Файл config.json обновлен под формат Happ (Sing-box)!")

if __name__ == "__main__":
    main()
