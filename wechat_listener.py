import logging
import time
import threading
import sys
import requests
import json
import os
from datetime import datetime
from wxauto import WeChat
import queue
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, simpledialog
from tkinter.font import Font

# 解决Windows控制台编码问题 - 修复NoneType错误
try:
    if sys.stdout is not None and hasattr(sys.stdout, 'encoding') and sys.stdout.encoding != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            os.environ["PYTHONIOENCODING"] = "utf-8"
    else:
        os.environ["PYTHONIOENCODING"] = "utf-8"
except Exception:
    os.environ["PYTHONIOENCODING"] = "utf-8"

# 添加打包后的资源路径
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# 日志队列用于在UI中显示日志
log_queue = queue.Queue()

# 配置日志
class QueueHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue
        
    def emit(self, record):
        self.log_queue.put(self.format(record))

def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    
    if getattr(sys, 'frozen', False):
        log_file = resource_path("wechat_listener.log")
    else:
        log_file = "wechat_listener.log"
    
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    queue_handler = QueueHandler(log_queue)
    queue_handler.setFormatter(formatter)
    logger.addHandler(queue_handler)
    
    return logger

logger = setup_logging()

class DeepSeekAPI:
    BASE_URL = "https://api.deepseek.com/chat/completions"
    API_KEY = None  # 初始化为None，将在UI中设置
    
    @classmethod
    def set_api_key(cls, api_key):
        cls.API_KEY = api_key
        logger.info("DeepSeek API密钥已设置")
    
    @staticmethod
    def get_reply(message, retries=2):
        if not DeepSeekAPI.API_KEY:
            logger.error("API密钥未设置，无法请求")
            return "❌ 服务未配置，请先设置API密钥"
            
        for attempt in range(retries + 1):
            try:
                headers = {
                    "Authorization": f"Bearer {DeepSeekAPI.API_KEY}",
                    "Content-Type": "application/json"
                }
                
                payload = {
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": "你是一个乐于助人的助手"},
                        {"role": "user", "content": message}
                    ],
                    "temperature": 0.7,
                    "max_tokens": 2000,
                    "stream": False
                }
                
                timeout = 15 + (attempt * 5)
                logger.info(f"API请求尝试 #{attempt+1} (超时: {timeout}秒)")
                response = requests.post(DeepSeekAPI.BASE_URL, headers=headers, json=payload, timeout=timeout)
                response.raise_for_status()
                
                data = response.json()
                
                if data.get("choices"):
                    reply_content = data["choices"][0]["message"]["content"]
                    return f"🤖【DeepSeek生成】\n{reply_content}"
                else:
                    logger.error(f"API返回格式错误: {data}")
                    return "我还在思考中，请稍后再试"
                    
            except requests.exceptions.Timeout:
                if attempt < retries:
                    logger.warning(f"API请求超时，将在{1 + attempt}秒后重试...")
                    time.sleep(1 + attempt)
                    continue
                else:
                    logger.error("API请求超时，已达最大重试次数")
                    return "请求超时，请稍后再试"
                    
            except requests.exceptions.RequestException as e:
                logger.error(f"API请求失败: {e}")
                if attempt < retries:
                    time.sleep(1)
                    continue
                else:
                    return "网络连接出现问题"
                    
            except Exception as e:
                logger.error(f"处理API响应时出错: {e}")
                return "处理消息时发生错误"
        
        return "服务暂时不可用，请稍后再试"

class WeChatListener:
    def __init__(self, listen_list, interval=1.0, 
                 time_report=False, time_report_who='文件传输助手', time_report_message="整点报时: {time}",
                 max_message_length=2000):
        self.wx = WeChat()
        self.listen_list = listen_list
        self.interval = interval
        self.running = False
        self.last_message_time = {}
        self.max_message_length = max_message_length
        self.start_time = None
        self.self_name = None
        
        try:
            self.self_name = self.wx.GetSelfInfo()['nickname']
            logger.info(f"获取到自己的昵称: {self.self_name}")
        except Exception as e:
            logger.error(f"获取自己昵称失败: {e}")
            self.self_name = "未知用户"
        
        self.time_report = time_report
        self.time_report_who = time_report_who
        self.time_report_message = time_report_message
        self.last_reported_hour = -1
        
        try:
            chats = self.wx.GetSessionList()
            logger.info(f"初始化成功，当前聊天窗口: {chats}")
        except AttributeError:
            try:
                chats = self.wx.GetAllChats()
                logger.info(f"初始化成功，当前聊天窗口: {chats}")
            except Exception:
                logger.warning("获取聊天窗口失败")
        
        for contact in self.listen_list:
            try:
                self.wx.AddListenChat(who=contact)
                logger.info(f"成功添加监听对象: {contact}")
            except Exception as e:
                logger.error(f"添加监听对象失败 {contact}: {e}")
    
    def process_message(self, chat, msg):
        who = chat.who
        msgtype = msg.type
        content = msg.content
        
        if msg.sender == self.self_name:
            logger.info(f"跳过自己发送的消息【{who}】: {content[:20]}...")
            return
        
        self.last_message_time[who] = datetime.now()
        logger.info(f'【{who}】发送消息: {content}')
        
        skip_keywords = ["以下为新消息", "收到请回复", "补充通知", "网络连接出现问题"]
        if any(keyword in content for keyword in skip_keywords):
            logger.info(f"跳过系统消息或错误消息: {content[:20]}...")
            return
        
        if msgtype == 'friend' and who in self.listen_list:
            try:
                api_reply = DeepSeekAPI.get_reply(content)
                logger.info(f'DeepSeek API回复内容: {api_reply}')
                
                if len(api_reply) > self.max_message_length:
                    self.send_long_message(chat, api_reply)
                else:
                    chat.SendMsg(api_reply)
                    logger.info(f'已回复【{who}】')
            except Exception as e:
                logger.error(f'回复消息失败【{who}】: {e}')
                try:
                    chat.SendMsg("抱歉，处理消息时出了点问题，请再试一次")
                except:
                    pass
    
    def send_long_message(self, chat, message):
        parts = []
        while message:
            if len(message) > self.max_message_length:
                split_index = message.rfind('\n', 0, self.max_message_length)
                if split_index == -1:
                    split_index = self.max_message_length
                part = message[:split_index]
                message = message[split_index:]
            else:
                part = message
                message = ""
            parts.append(part)
        
        for i, part in enumerate(parts):
            try:
                if i > 0 and "🤖【DeepSeek生成】" in part:
                    part = part.replace("🤖【DeepSeek生成】\n", "")
                chat.SendMsg(part)
                logger.info(f'已发送第 {i+1}/{len(parts)} 段回复给【{chat.who}】')
                time.sleep(0.5)
            except Exception as e:
                logger.error(f'发送长消息失败: {e}')
    
    def send_time_report(self):
        try:
            now = datetime.now()
            current_hour = now.hour
            
            if now.minute == 0 and now.second < 10 and current_hour != self.last_reported_hour:
                formatted_time = now.strftime("%Y年%m月%d日 %H:%M:%S")
                message = self.time_report_message.format(time=formatted_time)
                
                self.wx.SendMsg(msg=message, who=self.time_report_who)
                logger.info(f'已发送整点报时给【{self.time_report_who}】')
                self.last_reported_hour = current_hour
                
        except Exception as e:
            logger.error(f'发送整点报时失败: {e}')
    
    def listen_messages(self):
        logger.info("开始监听消息...")
        wait = self.interval
        
        try:
            self.wx.GetListenMessage()
            logger.info("已清空启动前的历史消息")
        except Exception as e:
            logger.error(f"清空历史消息失败: {e}")
        
        while self.running:
            try:
                if self.time_report:
                    self.send_time_report()
                
                msgs = self.wx.GetListenMessage()
                for chat in msgs:
                    if chat.who in self.listen_list:
                        one_msgs = msgs.get(chat)
                        for msg in one_msgs:
                            self.process_message(chat, msg)
                
                time.sleep(wait)
            except Exception as e:
                logger.error(f"监听过程中出错: {e}")
                time.sleep(5)
    
    def start_listening(self):
        if not self.running:
            self.running = True
            self.start_time = datetime.now()
            logger.info(f"监听开始时间: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            self.listener_thread = threading.Thread(target=self.listen_messages)
            self.listener_thread.daemon = True
            self.listener_thread.start()
            logger.info("微信监听服务已启动")
            if self.time_report:
                logger.info(f"整点报时功能已启用，接收对象: {self.time_report_who}")
    
    def stop_listening(self):
        if self.running:
            self.running = False
            if self.listener_thread.is_alive():
                self.listener_thread.join(timeout=2.0)
            logger.info("微信监听服务已停止")

class WeChatListenerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("微信智能助手")
        self.root.geometry("900x700")  # 增加高度以适应API密钥输入区域
        self.root.resizable(True, True)
        
        # 设置应用图标
        try:
            self.root.iconbitmap(resource_path("wechat.ico"))
        except:
            pass
        
        # 创建自定义样式
        self.create_styles()
        
        # 创建监听器实例
        self.listener = None
        
        # 创建UI
        self.create_widgets()
        
        # 设置日志更新定时器
        self.update_logs()
        
        # 设置关闭窗口时的处理
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
    
    def create_styles(self):
        """创建自定义样式"""
        # 标题字体
        self.title_font = Font(family="Microsoft YaHei", size=14, weight="bold")
        
        # 按钮样式
        style = ttk.Style()
        style.theme_use("clam")  # 使用clam主题作为基础
        
        # 配置颜色
        style.configure(".", background="#f8f9fa", foreground="#333333")
        style.configure("TFrame", background="#f8f9fa")
        style.configure("TLabelFrame", background="#f8f9fa", relief=tk.GROOVE, borderwidth=1)
        style.configure("TLabel", background="#f8f9fa", foreground="#333333")
        style.configure("TButton", font=("Microsoft YaHei", 10), padding=6, background="#e9ecef", borderwidth=1)
        
        # 主要按钮样式
        style.configure("Primary.TButton", 
                        font=("Microsoft YaHei", 10, "bold"), 
                        padding=6, 
                        foreground="white", 
                        background="#0d6efd")
        style.map("Primary.TButton", 
                 foreground=[('pressed', 'white'), ('active', 'white')],
                 background=[('pressed', '#0b5ed7'), ('active', '#0d6efd')])
        
        # 危险按钮样式
        style.configure("Danger.TButton", 
                        font=("Microsoft YaHei", 10), 
                        padding=6, 
                        foreground="white", 
                        background="#dc3545")
        style.map("Danger.TButton", 
                 foreground=[('pressed', 'white'), ('active', 'white')],
                 background=[('pressed', '#bb2d3b'), ('active', '#dc3545')])
        
        # 列表样式
        style.configure("Listbox", font=("Microsoft YaHei", 10), background="white", relief=tk.FLAT)
        style.configure("TCombobox", fieldbackground="white", background="white")
        
        # 配置日志区域
        style.configure("Log.TFrame", background="#ffffff")
    
    def create_widgets(self):
        """创建界面控件"""
        # 主容器
        main_container = ttk.Frame(self.root, padding=15)
        main_container.pack(fill=tk.BOTH, expand=True)
        
        # 标题区域
        header_frame = ttk.Frame(main_container)
        header_frame.pack(fill=tk.X, pady=(0, 15))
        
        ttk.Label(header_frame, text="微信智能助手", font=self.title_font, 
                 foreground="#0d6efd").pack(side=tk.LEFT)
        
        # 状态指示器
        self.status_indicator = ttk.Label(header_frame, text="● 就绪", foreground="#198754")
        self.status_indicator.pack(side=tk.RIGHT, padx=10)
        
        # API密钥区域
        api_frame = ttk.LabelFrame(main_container, text="API密钥设置", padding=10)
        api_frame.pack(fill=tk.X, pady=(0, 15))
        
        # API密钥输入框
        api_container = ttk.Frame(api_frame)
        api_container.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Label(api_container, text="DeepSeek API密钥:").pack(side=tk.LEFT, padx=(0, 10))
        
        self.api_key_var = tk.StringVar()
        self.api_entry = ttk.Entry(
            api_container, 
            textvariable=self.api_key_var, 
            width=50,
            font=("Consolas", 10)
        )
        self.api_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        # 显示/隐藏切换按钮
        self.show_api_key = tk.BooleanVar(value=False)
        self.toggle_btn = ttk.Checkbutton(
            api_container, 
            text="显示", 
            variable=self.show_api_key,
            command=self.toggle_api_visibility
        )
        self.toggle_btn.pack(side=tk.LEFT)
        
        # 内容区域 - 两列布局
        content_frame = ttk.Frame(main_container)
        content_frame.pack(fill=tk.BOTH, expand=True)
        
        # 左侧控制面板
        control_frame = ttk.LabelFrame(content_frame, text="控制面板", padding=15)
        control_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 15))
        
        # 监听设置
        ttk.Label(control_frame, text="监听对象:").pack(anchor=tk.W, pady=(0, 5))
        
        # 带滚动条的监听列表
        list_container = ttk.Frame(control_frame)
        list_container.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(list_container)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.listen_listbox = tk.Listbox(
            list_container, 
            yscrollcommand=scrollbar.set,
            height=8,
            selectbackground="#d1e7ff",
            selectmode=tk.SINGLE,
            font=("Microsoft YaHei", 10),
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground="#ced4da",
            highlightcolor="#86b7fe"
        )
        self.listen_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.listen_listbox.yview)
        
        # 添加一些默认联系人
        for contact in ["文件传输助手", "微信团队"]:
            self.listen_listbox.insert(tk.END, contact)
        
        # 按钮区域
        button_frame = ttk.Frame(control_frame)
        button_frame.pack(fill=tk.X, pady=10)
        
        ttk.Button(
            button_frame, 
            text="添加联系人", 
            command=self.add_listener,
            style="TButton"
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        
        ttk.Button(
            button_frame, 
            text="移除选中", 
            command=self.remove_listener,
            style="TButton"
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        
        # 控制按钮
        self.start_button = ttk.Button(
            control_frame, 
            text="开始监听", 
            command=self.start_listening, 
            style="Primary.TButton"
        )
        self.start_button.pack(fill=tk.X, pady=(10, 5))
        
        self.stop_button = ttk.Button(
            control_frame, 
            text="停止监听", 
            command=self.stop_listening, 
            state=tk.DISABLED,
            style="Danger.TButton"
        )
        self.stop_button.pack(fill=tk.X, pady=5)
        
        ttk.Button(
            control_frame, 
            text="清空日志", 
            command=self.clear_logs,
            style="TButton"
        ).pack(fill=tk.X, pady=5)
        
        # 右侧日志区域
        log_frame = ttk.LabelFrame(content_frame, text="运行日志", padding=10)
        log_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        self.log_text = scrolledtext.ScrolledText(
            log_frame, 
            wrap=tk.WORD,
            font=("Consolas", 10),
            bg="#ffffff",
            padx=10,
            pady=10,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground="#ced4da"
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.log_text.configure(state='disabled')
        
        # 创建日志颜色标签
        self.log_text.tag_configure("error", foreground="#dc3545")
        self.log_text.tag_configure("warning", foreground="#fd7e14")
        self.log_text.tag_configure("info", foreground="#0d6efd")
        self.log_text.tag_configure("success", foreground="#198754")
        
        # 底部状态栏
        status_bar = ttk.Frame(self.root, relief=tk.SUNKEN)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.status_var = tk.StringVar()
        self.status_var.set("就绪 | 欢迎使用微信智能助手 | 请先设置API密钥")
        status_label = ttk.Label(status_bar, textvariable=self.status_var, anchor=tk.W)
        status_label.pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)
        
        # 版本信息
        ttk.Label(status_bar, text="v1.1 | DeepSeek智能助手", anchor=tk.E).pack(side=tk.RIGHT, padx=10)
    
    def toggle_api_visibility(self):
        """切换API密钥的显示/隐藏"""
        if self.show_api_key.get():
            self.api_entry.config(show="")
            self.toggle_btn.config(text="隐藏")
        else:
            self.api_entry.config(show="•")
            self.toggle_btn.config(text="显示")
    
    def add_listener(self):
        """添加监听对象"""
        contact = simpledialog.askstring("添加监听对象", "请输入要监听的微信昵称:", parent=self.root)
        if contact and contact not in self.listen_listbox.get(0, tk.END):
            self.listen_listbox.insert(tk.END, contact)
            self.status_var.set(f"已添加监听对象: {contact}")
    
    def remove_listener(self):
        """删除选中的监听对象"""
        selected = self.listen_listbox.curselection()
        if selected:
            contact = self.listen_listbox.get(selected[0])
            self.listen_listbox.delete(selected[0])
            self.status_var.set(f"已移除监听对象: {contact}")
    
    def start_listening(self):
        """开始监听"""
        # 检查API密钥是否设置
        api_key = self.api_key_var.get().strip()
        if not api_key:
            messagebox.showwarning("警告", "请先设置DeepSeek API密钥!", parent=self.root)
            self.status_var.set("错误: 未设置API密钥")
            return
        
        DeepSeekAPI.set_api_key(api_key)
        
        listen_list = self.listen_listbox.get(0, tk.END)
        if not listen_list:
            messagebox.showwarning("警告", "请至少添加一个监听对象!", parent=self.root)
            self.status_var.set("错误: 未添加监听对象")
            return
        
        try:
            self.listener = WeChatListener(
                listen_list=list(listen_list),
                time_report=True,
                time_report_who=list(listen_list)[0],
                time_report_message="⏰ 现在是 {time}，整点报时！"
            )
            
            self.listener.start_listening()
            
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.NORMAL)
            self.status_indicator.config(text="● 运行中", foreground="#198754")
            self.status_var.set(f"正在监听 {len(listen_list)} 个联系人...")
            logger.info(f"开始监听: {', '.join(listen_list)}")
            
        except Exception as e:
            logger.error(f"启动监听失败: {e}")
            messagebox.showerror("错误", f"启动监听失败: {str(e)}", parent=self.root)
            self.status_var.set(f"错误: {str(e)}")
    
    def stop_listening(self):
        """停止监听"""
        if self.listener:
            self.listener.stop_listening()
            self.listener = None
            
            self.start_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
            self.status_indicator.config(text="● 已停止", foreground="#dc3545")
            self.status_var.set("监听已停止")
            logger.info("监听已停止")
    
    def clear_logs(self):
        """清空日志"""
        self.log_text.configure(state='normal')
        self.log_text.delete(1.0, tk.END)
        self.log_text.configure(state='disabled')
        self.status_var.set("日志已清空")
    
    def update_logs(self):
        """更新日志显示"""
        while not log_queue.empty():
            log_entry = log_queue.get()
            self.log_text.configure(state='normal')
            self.log_text.insert(tk.END, log_entry + "\n")
            
            # 根据日志级别设置颜色
            if "ERROR" in log_entry:
                self.log_text.tag_add("error", "end-2c linestart", "end-1c")
            elif "WARNING" in log_entry:
                self.log_text.tag_add("warning", "end-2c linestart", "end-1c")
            elif "INFO" in log_entry:
                self.log_text.tag_add("info", "end-2c linestart", "end-1c")
            elif "成功" in log_entry or "开始" in log_entry:
                self.log_text.tag_add("success", "end-2c linestart", "end-1c")
            
            self.log_text.see(tk.END)
            self.log_text.configure(state='disabled')
            log_queue.task_done()
        
        self.root.after(100, self.update_logs)
    
    def on_closing(self):
        """关闭窗口时的处理"""
        if self.listener and self.listener.running:
            if messagebox.askokcancel("退出", "监听仍在运行，确定要退出吗?", parent=self.root):
                self.stop_listening()
                self.root.destroy()
        else:
            self.root.destroy()

# 主程序
if __name__ == "__main__":
    root = tk.Tk()
    app = WeChatListenerApp(root)
    root.mainloop()