import json
import time
import requests
import config
import sys
import os
from datetime import datetime, timedelta

def get_log_path():
    if getattr(sys, 'frozen', False):
        # Если запущен как exe
        return os.path.join(os.path.dirname(sys.executable), 'vk_limits.log')
    else:
        # Если запущен как скрипт
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vk_limits.log')

LOG_FILE = get_log_path()

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

def vk_api_request(method, params, interrupt):
    """Улучшенный запрос к API с обработкой прерываний и лимитов"""
    params.update({
        'access_token': config.config["ACCESS_TOKEN"],
        'v': config.config["VERSION"],
        'timestamp': int(time.time()),
        'random_id': int(time.time() * 1000)
    })
    
    try:
        response = requests.get(VK_API_URL + method, params=params, timeout=30)
        result = response.json()
        
        if 'error' in result:
            error = result['error']
            error_code = error.get('error_code')
            
            # Обработка флуд-контроля и Rate Limit
            if error_code in [9, 29]:
                # Динамическая задержка: начнем с 5 сек, удваиваем при каждом повторе (макс 300 сек)
                current_delay = getattr(vk_api_request, 'current_delay', 5)
                delay = min(current_delay * 2, 300) if error_code == 29 else 10
                vk_api_request.current_delay = delay
                
                print(f"⏳ Лимит запросов ({error['error_msg']}). Пауза {delay} сек...")
                for _ in range(delay):
                    if interrupt.interrupted:
                        print("🛑 Обнаружено прерывание во время ожидания")
                        return None
                    time.sleep(1)
                
                return vk_api_request(method, params, interrupt)
            
            if error_code == 15:
                print("⏩ Обнаружен создатель группы. Удалите себя вручную через настройки сообщества")
            else:
                print(f"⛔ Ошибка API {error_code}: {error['error_msg']}")
            return None
            
        # Сброс задержки при успешном запросе
        vk_api_request.current_delay = 5
        return result
        
    except Exception as e:
        print(f"⚠️ Ошибка соединения: {e}")
        return None

def safe_delete_post(group_id, post_id, limits, interrupt):
    if interrupt.interrupted:
        return False
    if limits['posts_deleted'] >= config.config["MAX_POSTS_PER_HOUR"]:
        return False
    
    result = vk_api_request('wall.delete', {
        'owner_id': group_id,
        'post_id': post_id
    }, interrupt)  # Добавлен параметр interrupt
    
    if result and 'response' in result and result['response'] == 1:
        limits['posts_deleted'] += 1
        time.sleep(config.config["DELAY"])
        return True
    return False

def safe_remove_user(group_id, user_id, limits, interrupt):
    if interrupt.interrupted:
        return False
        
    if limits['users_deleted'] >= config.config["MAX_USERS_PER_DAY"]:
        return False
    
    result = vk_api_request('groups.removeUser', {
        'group_id': abs(group_id),
        'user_id': user_id
    }, interrupt)
    
    if not result:
        return False
        
    if result.get('response') == 1:
        limits['users_deleted'] += 1
        time.sleep(config.config.get("REQUEST_DELAY", 3))
        return True
        
    error = result.get('error', {})
    error_code = error.get('error_code')
    
    if error_code in [15, 7]:  # Админы/создатели
        print(f"⏩ Обнаружен создатель группы. Удалите себя вручную через настройки сообщества")
        return False
    elif error_code == 9:  # Флуд-контроль
        delay = config.config.get("FLOOD_DELAY", 10)
        print(f"⏳ Флуд-контроль. Ждем {delay} сек...")
        time.sleep(delay)
        return safe_remove_user(group_id, user_id, limits, interrupt)
    else:
        print(f"Ошибка удаления {user_id}: {error.get('error_msg', 'Unknown error')}")
        return False
    
def delete_posts(limits, interrupt):
    offset = 0
    count = 100
    deleted = 0
    max_attempts = 3
    attempts = 0
    
    while not interrupt.interrupted and attempts < max_attempts:
        if limits['posts_deleted'] >= config.config["MAX_POSTS_PER_HOUR"]:
            reset_time = datetime.fromtimestamp(limits['last_post_reset'] + 3600)
            print(f"\nЛимит постов достигнут! Доступно после {reset_time.strftime('%d.%m.%Y %H:%M')}")
            break
            
        response = vk_api_request('wall.get', {
            'owner_id': int(config.config["GROUP_ID"]),
            'count': count,
            'offset': offset
        }, interrupt)  # Добавлен параметр interrupt
        
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
    count = min(100, config.config.get("MEMBERS_PER_REQUEST", 100))
    removed = 0
    retry_count = 0
    max_retries = config.config.get("API_RETRY_LIMIT", 3)
    creator_detected = False
    
    print("\n[2] Удаление подписчиков...")
    
    if limits['users_deleted'] >= config.config["MAX_USERS_PER_DAY"]:
        reset_time = datetime.fromtimestamp(limits['last_user_reset']) + timedelta(days=1)
        print(f"⏳ Лимит удалений достигнут! Доступно после {reset_time.strftime('%d.%m.%Y %H:%M')}")
        return 0
    
    while not interrupt.interrupted and retry_count < max_retries:
        if interrupt.interrupted:
            print("🛑 Обнаружено прерывание!")
            break
            
        response = vk_api_request('groups.getMembers', {
            'group_id': abs(int(config.config["GROUP_ID"])),
            'count': count,
            'offset': offset,
            'fields': 'role'
        }, interrupt)
        
        if not response:
            retry_count += 1
            time.sleep(5)
            continue
            
        if 'error' in response:
            error = response['error']
            print(f"⛔ Ошибка API [{error['error_code']}]: {error['error_msg']}")
            retry_count += 1
            continue
            
        members = response.get('response', {}).get('items', [])
        if not members:
            if removed > 0:
                if creator_detected:
                    print("\n\n🎉 Поздравляю! Все подписчики удалены!")
                    print("Для завершения удалите себя вручную через:")
                    print("Управление сообществом → Участники → Исключить")
                else:
                    print("\nПодписчики закончились")
                    print("\n🎉 Поздравляю! Все подписчики удалены!")
                    print("Для завершения удалите себя вручную через:")
                    print("Управление сообществом → Участники → Исключить")
            else:
                print("\nВ сообществе нет подписчиков для удаления")
            break
            
        for member in members:
            if interrupt.interrupted:
                break
                
            user_id = member['id']
            role = member.get('role', 'member')
            
            if role == 'creator':
                creator_detected = True
                continue
                
            if safe_remove_user(int(config.config["GROUP_ID"]), user_id, limits, interrupt):
                removed += 1
                print(f"❌ Удалён подписчик {user_id} ({removed}/{config.config['MAX_USERS_PER_DAY']})")
                
                if limits['users_deleted'] >= config.config["MAX_USERS_PER_DAY"]:
                    print("⚠️ Достигнут дневной лимит удалений!")
                    break
                    
        offset += len(members)
        retry_count = 0

    return removed

def main(interrupt):
    if getattr(sys, 'frozen', False):
        import shutil
        temp_dir = os.path.join(os.environ.get('TEMP', ''), 'vk_cleaner_cache')
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

    try:
        limits = manage_limits('read')
        
        print("\n=== VK UnSub & PostDelete ===")
        print(f"Лимиты:")
        print(f"📝 Постов: {limits['posts_deleted']}/{config.config['MAX_POSTS_PER_HOUR']} (час)")
        print(f"👥 Подписчиков: {limits['users_deleted']}/{config.config['MAX_USERS_PER_DAY']} (день)")
        
        # Обработка постов
        if not interrupt.interrupted:
            print("\n[1] Удаление постов...")
            deleted_posts = delete_posts(limits, interrupt)
            print(f"\nУдалено постов: {deleted_posts}")
        
        # Обработка подписчиков
        if not interrupt.interrupted:
            print("\n[2] Удаление подписчиков...")
            removed_users = remove_users(limits, interrupt)
            print(f"\nУдалено подписчиков: {removed_users}")
            
    except KeyboardInterrupt:
        print("\n🛑 Получен сигнал прерывания!")
        interrupt.handler()
    except Exception as e:
        print(f"\n🔥 Критическая ошибка: {e}")
    finally:
        if 'limits' in locals():
            manage_limits('write', limits)
            print("\n📊 Итоговые лимиты:")
            print(f"📝 Постов: {limits['posts_deleted']}/{config.config['MAX_POSTS_PER_HOUR']}")
            print(f"👥 Подписчиков: {limits['users_deleted']}/{config.config['MAX_USERS_PER_DAY']}")
        print("\n📊 Статистика сохранена!")
