import socket
import sys
from urllib.parse import urlparse, parse_qs, unquote, urlencode
import requests

# =====================================================================
# ВСТАВЬТЕ СЮДА ВАШУ ССЫЛКУ С ГИТХАБА (ГДЕ ЛЕЖАТ СТРОКИ vless://)
SUBSCRIBE_URL = "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/Vless-Reality-White-Lists-Rus-Mobile.txt"
# =====================================================================

def fetch_links(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return [line.strip() for line in response.text.splitlines() if line.strip()]
    except Exception as e:
        print(f"Ошибка при скачивании списка серверов: {e}")
        sys.exit(1)

def parse_vless_link(link):
    if not isinstance(link, str) or not link.startswith("vless://"):
        return None
    try:
        main_part, *name_part = link.split('#')
        name = unquote(name_part[0]) if name_part else "Node"
        
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
            "flow": get_param("flow"),
            "name": name
        }
    except Exception as e:
        print(f"Ошибка парсинга: {e}")
        return None

def check_server_port(ip, port, timeout=2):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except Exception:
        return False

def main():
    print("1. Скачивание списка...")
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
    
    print("\n2. Поиск рабочего RU...")
    for node in ru_pool:
        if check_server_port(node["ip"], node["port"]):
            active_ru = node
            break
            
    print("\n3. Поиск рабочего Зарубежного...")
    for node in foreign_pool:
        if check_server_port(node["ip"], node["port"]):
            active_foreign = node
            break
            
    if not active_ru or not active_foreign:
        print("[ОШИБКА] Нет рабочей пары серверов.")
        sys.exit(1)
        
    # Собираем параметры зарубежного сервера
    params = {
        "type": active_foreign["network"],
        "security": active_foreign["security"],
    }
    if active_foreign["security"] == "reality":
        params.update({
            "sni": active_foreign["sni"],
            "pbk": active_foreign["pbk"],
            "sid": active_foreign["sid"]
        })
    if active_foreign["network"] == "ws":
        params.update({"path": active_foreign["path"], "host": active_foreign["host"]})
        
    # Магия для HAP: передаем данные транзитного RU-сервера прямо внутрь ссылки
    params["outboundProxy"] = f"vless://{active_ru['id']}@{active_ru['ip']}:{active_ru['port']}?type={active_ru['network']}&security={active_ru['security']}&sni={active_ru['sni']}&pbk={active_ru['pbk']}&sid={active_ru['sid']}"
    
    # Итоговая ссылка
    chain_link = f"vless://{active_foreign['id']}@{active_foreign['ip']}:{active_foreign['port']}?{urlencode(params)}#Chain_VPN"
    
    # Сохраняем в текстовый файл, который HAP скушает без проблем
    with open("links.txt", "w", encoding="utf-8") as f:
        f.write(chain_link + "\n")
        
    print("\n[ГОТОВО] Ссылка успешно создана в файле links.txt!")

if __name__ == "__main__":
    main()
