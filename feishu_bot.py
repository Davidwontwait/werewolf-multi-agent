import os
import time
import requests
import json

class FeishuBot:
    def __init__(self):
        self.app_id = os.getenv("FEISHU_APP_ID")
        self.app_secret = os.getenv("FEISHU_APP_SECRET")
        self.chat_id = os.getenv("FEISHU_HOME_CHANNEL")
        self.access_token = None
        self.token_expire_time = 0  # token 过期时间戳
    
    def get_access_token(self):
        """获取 access_token，带过期时间管理"""
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }
        response = requests.post(url, json=payload)
        data = response.json()
        if data.get("code") == 0:
            self.access_token = data["tenant_access_token"]
            # 飞书 token 有效期 2 小时，提前 5 分钟刷新
            self.token_expire_time = time.time() + data.get("expire", 7200) - 300
            return True
        return False
    
    def _ensure_token(self):
        """确保 token 有效，过期则自动刷新"""
        if self.access_token is None or time.time() >= self.token_expire_time:
            return self.get_access_token()
        return True
    
    def send_message(self, text: str):
        """发送消息到飞书"""
        if not self._ensure_token():
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
        # token 过期错误码，自动刷新重试一次
        elif data.get("code") in (99991663, 99991664):
            self.access_token = None
            self.token_expire_time = 0
            if self._ensure_token():
                headers["Authorization"] = f"Bearer {self.access_token}"
                response = requests.post(url, headers=headers, params=params, json=payload)
                data = response.json()
                if data.get("code") == 0:
                    return True
        print(f"[飞书错误] {data}")
        return False

# 测试
if __name__ == "__main__":
    bot = FeishuBot()
    bot.send_message("🐺 狼人杀游戏测试消息")
    print("发送成功！")
