import json
import time
import requests
import config
from datetime import datetime, timedelta

LOG_FILE = 'vk_limits.log'
VK_API_URL = 'https://api.vk.com/method/'

class GracefulInterrupt:
    def __init__(self):
        self.interrupted = False

    def handler(self):
        self.interrupted = True

def manage_limits(action, data=None):
    if action == 'read':
        try:
            with open(LOG_FILE, 'r') as f:
                limits = json.load(f)
            
            current_time = time.time()
            if current_time - limits['last_user_reset'] > 86400:
                limits['users_deleted'] = 0
                limits['last_user_reset'] = current_time
            if current_time - limits['last_post_reset'] > 3600:
                limits['posts_deleted'] = 0
                limits['last_post_reset'] = current_time
            
            return limits
        except (FileNotFoundError, json.JSONDecodeError):
            return {
                'users_deleted': 0,
                'posts_deleted': 0,
                'last_user_reset': int(time.time()),
                'last_post_reset': int(time.time())
            }
    elif action == 'write':
        with open(LOG_FILE, 'w') as f:
            json.dump(data, f, indent=2)

def vk_api_request(method, params):
    params.update({
        'access_token': config.config["ACCESS_TOKEN"],
        'v': config.config["VERSION"]
    })
    
    try:
        response = requests.get(VK_API_URL + method, params=params, timeout=30)
        return response.json()
    except Exception as e:
        print(f"Ошибка API: {e}")
        return None

def safe_delete_post(group_id, post_id, limits, interrupt):
    if interrupt.interrupted:
        return False
        
    if limits['posts_deleted'] >= config.config["MAX_POSTS_PER_HOUR"]:
        reset_time = datetime.fromtimestamp(limits['last_post_reset'] + 3600)
        print(f"\nЛимит постов достигнут! Во избежание блокировки запустите скрипт после {reset_time.strftime('%d.%m.%Y %H:%M')}")
        return False
    
    result = vk_api_request('wall.delete', {
        'owner_id': group_id,
        'post_id': post_id
    })
    
    if result and 'response' in result and result['response'] == 1:
        limits['posts_deleted'] += 1
        time.sleep(config.config["DELAY"])
        return True
    return False

def safe_remove_user(group_id, user_id, limits, interrupt):
    if interrupt.interrupted:
        return False
        
    if limits['users_deleted'] >= config.config["MAX_USERS_PER_DAY"]:
        reset_time = datetime.fromtimestamp(limits['last_user_reset'] + 86400)
        print(f"\nЛимит подписчиков достигнут! Во избежание блокировки запустите скрипт после {reset_time.strftime('%d.%m.%Y %H:%M')}")
        return False
    
    result = vk_api_request('groups.removeUser', {
        'group_id': abs(group_id),
        'user_id': user_id
    })
    
    if result and 'response' in result and result['response'] == 1:
        limits['users_deleted'] += 1
        time.sleep(config.config["DELAY"])
        return True
    return False

def delete_posts(limits, interrupt):
    offset = 0
    count = 100
    deleted = 0
    max_attempts = 3
    attempts = 0
    
    while not interrupt.interrupted and attempts < max_attempts:
        if limits['posts_deleted'] >= config.config["MAX_POSTS_PER_HOUR"]:
            break
            
        response = vk_api_request('wall.get', {
            'owner_id': int(config.config["GROUP_ID"]),
            'count': count,
            'offset': offset
        })
        
        if not response:
            attempts += 1
            time.sleep(5)
            continue
            
        if 'items' not in response.get('response', {}):
            print("\nПосты закончились")
            break
            
        items = response['response']['items']
        if not items:
            print("\nБольше нет постов для удаления")
            break
            
        for post in items:
            if interrupt.interrupted or limits['posts_deleted'] >= config.config["MAX_POSTS_PER_HOUR"]:
                break
                
            if safe_delete_post(int(config.config["GROUP_ID"]), post['id'], limits, interrupt):
                deleted += 1
                print(f"Удален пост {post['id']} ({deleted} в этой сессии)")
        
        offset += count
        attempts = 0
        
    return deleted

def remove_users(limits, interrupt):
    offset = 0
    count = 1000
    removed = 0
    
    while not interrupt.interrupted:
        if limits['users_deleted'] >= config.config["MAX_USERS_PER_DAY"]:
            break
            
        response = vk_api_request('groups.getMembers', {
            'group_id': abs(int(config.config["GROUP_ID"])),
            'count': count,
            'offset': offset
        })
        
        if not response or 'items' not in response.get('response', {}):
            print("\nПодписчики закончились")
            break
            
        for user_id in response['response']['items']:
            if interrupt.interrupted or limits['users_deleted'] >= config.config["MAX_USERS_PER_DAY"]:
                break
                
            if safe_remove_user(int(config.config["GROUP_ID"]), user_id, limits, interrupt):
                removed += 1
                print(f"Удален подписчик {user_id} ({removed} в этой сессии)")
        
        offset += count
        
    return removed

def main(interrupt):
    limits = manage_limits('read')
    
    print("\n=== VK Cleaner ===")
    print(f"Лимиты:")
    print(f"Постов: {limits['posts_deleted']}/{config.config['MAX_POSTS_PER_HOUR']} (час)")
    print(f"Подписчиков: {limits['users_deleted']}/{config.config['MAX_USERS_PER_DAY']} (день)")
    
    try:
        print("\n[1] Удаление постов...")
        deleted_posts = delete_posts(limits, interrupt)
        print(f"\nУдалено постов в этой сессии: {deleted_posts}")
        
        if not interrupt.interrupted and limits['users_deleted'] < config.config["MAX_USERS_PER_DAY"]:
            print("\n[2] Удаление подписчиков...")
            removed_users = remove_users(limits, interrupt)
            print(f"\nУдалено подписчиков в этой сессии: {removed_users}")
        
    except Exception as e:
        print(f"\nОшибка: {e}")
    finally:
        manage_limits('write', limits)
        print("\nИтоговые лимиты:")
        print(f"Постов: {limits['posts_deleted']}/{config.config['MAX_POSTS_PER_HOUR']}")
        print(f"Подписчиков: {limits['users_deleted']}/{config.config['MAX_USERS_PER_DAY']}")
        print("\n📊 Статистика сохранена!")

if __name__ == "__main__":
    interrupt = GracefulInterrupt()
    main(interrupt)