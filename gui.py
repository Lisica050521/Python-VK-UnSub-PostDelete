import customtkinter as ctk
import threading
import config
from vk_cleaner import main, GracefulInterrupt
import sys
import requests
import queue

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

class ConsoleText(ctk.CTkTextbox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bind("<Control-c>", self.copy_text)
        self.bind("<Control-v>", self.paste_text)
        
    def copy_text(self, event=None):
        self.clipboard_clear()
        text = self.get("sel.first", "sel.last")
        self.clipboard_append(text)
        return "break"
        
    def paste_text(self, event=None):
        text = self.clipboard_get()
        self.insert("insert", text)
        return "break"

class VKCleanerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("VK Cleaner GUI")
        self.geometry("800x600")
        
        self.log_queue = queue.Queue()
        self.thread = None
        self.interrupt = GracefulInterrupt()
        self.setup_ui()
        self.after(100, self.process_queue)

    def setup_ui(self):
        self.main_frame = ctk.CTkFrame(self)
        self.main_frame.pack(pady=20, padx=20, fill="both", expand=True)

        ctk.CTkLabel(self.main_frame, text="Токен VK:").pack(pady=(10, 0))
        self.token_entry = ctk.CTkEntry(self.main_frame, width=400)
        self.token_entry.pack()
        self.token_entry.insert(0, config.config["ACCESS_TOKEN"])

        ctk.CTkLabel(self.main_frame, text="ID Группы:").pack(pady=(10, 0))
        self.group_id_entry = ctk.CTkEntry(self.main_frame, width=400)
        self.group_id_entry.pack()
        self.group_id_entry.insert(0, config.config["GROUP_ID"])

        self.btn_frame = ctk.CTkFrame(self.main_frame)
        self.btn_frame.pack(pady=10)
        ctk.CTkButton(self.btn_frame, text="Сохранить", command=self.save_config).pack(side="left", padx=5)
        ctk.CTkButton(self.btn_frame, text="Проверить токен", command=self.check_token).pack(side="left", padx=5)

        self.log_text = ConsoleText(self.main_frame, width=750, height=300, 
                                 wrap="word", font=("Consolas", 12))
        self.log_text.pack(pady=10, fill="both", expand=True)

        self.control_frame = ctk.CTkFrame(self.main_frame)
        self.control_frame.pack(pady=10)
        self.start_btn = ctk.CTkButton(self.control_frame, text="Старт", 
                                     command=self.start_cleaner, fg_color="green")
        self.start_btn.pack(side="left", padx=20)
        self.stop_btn = ctk.CTkButton(self.control_frame, text="Стоп", 
                                    command=self.stop_cleaner, fg_color="red")
        self.stop_btn.pack(side="left", padx=20)

    def save_config(self):
        config.config["ACCESS_TOKEN"] = self.token_entry.get()
        config.config["GROUP_ID"] = self.group_id_entry.get()
        config.save_config(config.config)
        self.log("Настройки сохранены!")

    def check_token(self):
        token = config.config["ACCESS_TOKEN"]
        if not token:
            self.log("Ошибка: токен не введен!")
            return
            
        try:
            response = requests.get('https://api.vk.com/method/users.get', 
                                 params={'access_token': token, 'v': '5.131'},
                                 timeout=10)
            data = response.json()
            
            if 'response' in data:
                self.log(f"✓ Токен действителен! ID: {data['response'][0]['id']}")
            else:
                self.log(f"× Ошибка: {data.get('error', {}).get('error_msg', 'Неизвестная ошибка')}")
        except Exception as e:
            self.log(f"! Ошибка проверки: {str(e)}")

    def start_cleaner(self):
        if not config.config["GROUP_ID"]:
            self.log("Ошибка: введите ID группы!")
            return
            
        if self.thread and self.thread.is_alive():
            self.log("Процесс уже запущен!")
            return
            
        self.interrupt.interrupted = False
        self.thread = threading.Thread(target=self.run_cleaner, daemon=True)
        self.thread.start()

    def stop_cleaner(self):
        self.interrupt.interrupted = True
        self.log("Запрошена остановка...")

    def run_cleaner(self):
        old_stdout = sys.stdout
        sys.stdout = self
        
        try:
            main(self.interrupt)
        except Exception as e:
            self.log(f"Ошибка: {str(e)}")
        finally:
            sys.stdout = old_stdout

    def write(self, text):
        self.log_queue.put(text)

    def flush(self):
        pass

    def process_queue(self):
        while not self.log_queue.empty():
            text = self.log_queue.get()
            self.log_text.insert("end", text)
            self.log_text.see("end")
        self.after(100, self.process_queue)

    def log(self, message):
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")

if __name__ == "__main__":
    app = VKCleanerApp()
    app.mainloop()