import json
import socket
import sys
from urllib.parse import urlparse, parse_qs, unquote
import requests

# 1. Вставьте сюда URL вашей текстовой подписки с GitHub (где лежат строки vless://)
SUBSCRIBE_URL = "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/Vless-Reality-White-Lists-Rus-Mobile.txt"

def fetch_links(url):
    """Скачивает список ссылок из сети"""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.text.strip().splitlines()
    except Exception as e:
        print(f"Ошибка при скачивании списка серверов: {e}")
        sys.exit(1)

def parse_vless_link(link):
    """Разбирает вашу vless ссылку на параметры для Xray JSON"""
    if not link.startswith("vless://"):
        return None
    try:
        # Убираем хэштег с именем в конце, чтобы не мешал парсингу URL
        main_part, *name_part = link.split('#')
        name = unquote(name_part[0]) if name_part else "Без названия"
        
        parsed = urlparse(main_part)
        uuid = parsed.username
        hostname = parsed.hostname
        
        # Получаем чистый IP, если вместо него указан домен
        try:
            ip = socket.gethostbyname(hostname)
        except Exception:
            ip = hostname
            
        port = parsed.port
        queries = parse_qs(parsed.query)
        
        return {
            "ip": ip,
            "port": int(port),
            "id": uuid,
            # Извлекаем параметры шифрования Reality
            "sni": queries.get("sni", [""])[0],
            "pbk": queries.get("pbk", [""])[0],
            "sid": queries.get("sid", [""])[0],
            "flow": queries.get("flow", [""])[0],
            "name": name
        }
    except Exception as e:
        print(f"Не удалось распарсить ссылку {link[:30]}... Ошибка: {e}")
        return None

def get_server_country(ip):
    """Определяет страну сервера через бесплатное гео-API"""
    try:
        if ip.startswith("127.") or ip.startswith("192."):
            return "UNKNOWN"
        res = requests.get(f"http://ip-api.com{ip}", timeout=3).json()
        if res.get("status") == "success":
            return res.get("countryCode")  # Вернет "RU", "FI", "DE" и т.д.
    except Exception:
        pass
    return "UNKNOWN"

def check_server_port(ip, port, timeout=2):
    """Проверяет, открыт ли порт (сервер "жив")"""
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except Exception:
        return False

def build_xray_chain(ru_node, foreign_node):
    """Генерирует финальный JSON, заставляя заграничный сервер идти через РУ"""
    config = {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "port": 10808,  # Локальный порт SOCKS5 на вашем ПК
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": True}
            }
        ],
        "outbounds": [
            {
                "tag": "foreign-vps",
                "protocol": "vless",
                "settings": {
                    "vnext": [{
                        "address": foreign_node["ip"],
                        "port": foreign_node["port"],
                        "users": [{
                            "id": foreign_node["id"], 
                            "encryption": "none",
                            "flow": foreign_node["flow"] if foreign_node["flow"] else "xtls-rprx-vision"
                        }]
                    }]
                },
                "streamSettings": {
                    "network": "tcp",
                    "security": "reality",
                    "realitySettings": {
                        "show": False,
                        "fingerprint": "firefox",
                        "serverName": foreign_node["sni"],
                        "publicKey": foreign_node["pbk"],
                        "shortId": foreign_node["sid"]
                    },
                    "sockopt": {
                        "dialerProxy": "ru-transit"  # Связываем цепочку здесь
                    }
                }
            },
            {
                "tag": "ru-transit",
                "protocol": "vless",
                "settings": {
                    "vnext": [{
                        "address": ru_node["ip"],
                        "port": ru_node["port"],
                        "users": [{
                            "id": ru_node["id"], 
                            "encryption": "none",
                            "flow": ru_node["flow"] if ru_node["flow"] else "xtls-rprx-vision"
                        }]
                    }]
                },
                "streamSettings": {
                    "network": "tcp",
                    "security": "reality",
                    "realitySettings": {
                        "show": False,
                        "fingerprint": "firefox",
                        "serverName": ru_node["sni"],
                        "publicKey": ru_node["pbk"],
                        "shortId": ru_node["sid"]
                    }
                }
            }
        ]
    }
    return config

def main():
    print("1. Загрузка списка серверов...")
    raw_links = fetch_links(SUBSCRIBE_URL)
    print(f"Успешно загружено строк: {len(raw_links)}")
    
    ru_pool = []
    foreign_pool = []
    
    print("\n2. Анализ геолокации IP-адресов...")
    for link in raw_links:
        node = parse_vless_link(link)
        if not node:
            continue
            
        country = get_server_country(node["ip"])
        print(f"Сервер [{node['name']}] с IP {node['ip']} -> Локация: {country}")
        
        if country == "RU":
            ru_pool.append(node)
        elif country != "UNKNOWN":
            foreign_pool.append(node)
            
    print(f"\nСортировка завершена. Найдено серверов РФ: {len(ru_pool)}, Зарубежных: {len(foreign_pool)}")
    
    active_ru = None
    active_foreign = None
    
    print("\n3. Проверка доступности российских прокси...")
    for node in ru_pool:
        if check_server_port(node["ip"], node["port"]):
            active_ru = node
            print(f"-> Выбран рабочий RU сервер: {node['name']} ({node['ip']})")
            break
            
    print("\n4. Проверка доступности зарубежных прокси...")
    for node in foreign_pool:
        if check_server_port(node["ip"], node["port"]):
            active_foreign = node
            print(f"-> Выбран рабочий Зарубежный сервер: {node['name']} ({node['ip']})")
            break
            
    if not active_ru or not active_foreign:
        print("\n[ОШИБКА] Не удалось собрать цепочку. Нужен хотя бы 1 живой RU и 1 живой зарубежный сервер.")
        sys.exit(1)
        
    print(f"\n5. Сборка каскада: Вы -> {active_ru['ip']} -> {active_foreign['ip']}")
    final_json = build_xray_chain(active_ru, active_foreign)
    
    # Сохраняем готовый файл для клиента (например, Nekoray или v2rayN)
    with open("config.json", "w", encoding="utf-8") as f:
        json.dump(final_json, f, indent=4, ensure_ascii=False)
        
    print("\n[ГОТОВО] Скрипт создал файл config.json. Настройки успешно обновлены!")

if __name__ == "__main__":
    main()
