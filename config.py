import os
import json

CONFIG_FILE = "config.json"

DEFAULT_CONFIG = {
    "ACCESS_TOKEN": "",
    "GROUP_ID": "",
    "VERSION": "5.131",
    "MAX_USERS_PER_DAY": 100,
    "MAX_POSTS_PER_HOUR": 100,
    "DELAY": 2
}

def load_config():
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
    
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

def save_config(new_config):
    # Добавляем минус к GROUP_ID, если его нет и строка не пустая
    if "GROUP_ID" in new_config and new_config["GROUP_ID"] and not new_config["GROUP_ID"].startswith("-"):
        new_config["GROUP_ID"] = "-" + new_config["GROUP_ID"]
    
    with open(CONFIG_FILE, "w") as f:
        json.dump(new_config, f, indent=2)

config = load_config()