import os
import requests
import json

class FeishuBot:
    def __init__(self):
        self.app_id = os.getenv("FEISHU_APP_ID")
        self.app_secret = os.getenv("FEISHU_APP_SECRET")
        self.chat_id = os.getenv("FEISHU_HOME_CHANNEL")
        self.access_token = None
    
    def get_access_token(self):
        """获取 access_token"""
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }
        response = requests.post(url, json=payload)
        data = response.json()
        if data.get("code") == 0:
            self.access_token = data["tenant_access_token"]
            return True
        return False
    
    def send_message(self, text: str):
        """发送消息到飞书"""
        if not self.access_token:
            if not self.get_access_token():
                print(f"[飞书错误] 无法获取 access_token")
                return False
        
        url = "https://open.feishu.cn/open-apis/im/v1/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "receive_id": self.chat_id,
            "msg_type": "text",
            "content": json.dumps({"text": text})
        }
        params = {"receive_id_type": "chat_id"}
        
        response = requests.post(url, headers=headers, params=params, json=payload)
        data = response.json()
        if data.get("code") == 0:
            return True
        else:
            print(f"[飞书错误] {data}")
            return False

# 测试
if __name__ == "__main__":
    bot = FeishuBot()
    bot.send_message("🐺 狼人杀游戏测试消息")
    print("发送成功！")
