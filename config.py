import os
import json
from datetime import datetime

CONFIG_FILE = "config.json"

DEFAULT_CONFIG = {
    "ACCESS_TOKEN": "",
    "GROUP_ID": "",
    "VERSION": "5.131",
    "MAX_USERS_PER_DAY": 1000,       # Лимит удалений в день
    "MAX_POSTS_PER_HOUR": 100,       # Лимит удалений в час
    "DELAY": 1,                      # Основная задержка между операциями (сек)
    "REQUEST_DELAY": 3,              # Задержка между запросами (сек)
    "FLOOD_DELAY": 10,               # Задержка при флуд-контроле
    "MEMBERS_PER_REQUEST": 200,      # Участников за один запрос
    "POSTS_PER_REQUEST": 100,        # Постов за один запрос
    "API_RETRY_LIMIT": 3,            # Количество попыток при ошибках API
    "LAST_RATE_LIMIT": None          # Время последнего лимита
}

def load_config():
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    
    try:
        with open(CONFIG_FILE, "r", encoding='utf-8') as f:
            config = json.load(f)
            
            # Обновляем конфиг, если добавились новые параметры
            updated = False
            for key, value in DEFAULT_CONFIG.items():
                if key not in config:
                    config[key] = value
                    updated = True
            
            if updated:
                save_config(config)
                
            return config
            
    except Exception as e:
        print(f"Ошибка загрузки конфига: {e}")
        return DEFAULT_CONFIG.copy()

def save_config(new_config):
    # Валидация GROUP_ID
    if "GROUP_ID" in new_config and new_config["GROUP_ID"]:
        group_id = str(new_config["GROUP_ID"])
        if group_id.replace("-", "").isdigit():
            if not group_id.startswith("-"):
                new_config["GROUP_ID"] = "-" + group_id.lstrip("-")
        else:
            new_config["GROUP_ID"] = ""
    
    # Сохраняем время последнего лимита как строку
    if "LAST_RATE_LIMIT" in new_config and isinstance(new_config["LAST_RATE_LIMIT"], datetime):
        new_config["LAST_RATE_LIMIT"] = new_config["LAST_RATE_LIMIT"].isoformat()
    
    try:
        with open(CONFIG_FILE, "w", encoding='utf-8') as f:
            json.dump(new_config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Ошибка сохранения конфига: {e}")

def update_last_rate_limit():
    config = load_config()
    config["LAST_RATE_LIMIT"] = datetime.now().isoformat()
    save_config(config)

def get_rate_limit_delay():
    config = load_config()
    if not config.get("LAST_RATE_LIMIT"):
        return 0
        
    try:
        last_limit = datetime.fromisoformat(config["LAST_RATE_LIMIT"])
        seconds_passed = (datetime.now() - last_limit).total_seconds()
        return max(0, 3600 - seconds_passed)  # 1 час с последнего лимита
    except:
        return 0

config = load_config()