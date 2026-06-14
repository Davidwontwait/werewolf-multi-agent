import os

def load_env_file(path: str):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                key, val = line.split('=', 1)
                os.environ.setdefault(key, val.strip().strip('"').strip("'"))

load_env_file(os.path.join(os.getcwd(), ".env"))

try:
    from openai import OpenAI
except ImportError:
    raise SystemExit("缺少 openai 依赖，请先运行：pip install -r requirements.txt")

api_key = os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
if not api_key:
    raise SystemExit("请先设置 OPENAI_API_KEY 或 DASHSCOPE_API_KEY 环境变量")

client = OpenAI(
    api_key=api_key,
    base_url=os.getenv("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
)

response = client.chat.completions.create(
    model=os.getenv("WEREWOLF_MODEL", "deepseek-v4-pro"),
    messages=[
        {"role": "system", "content": "你是一个狼人杀玩家，身份是狼人。"},
        {"role": "user", "content": "你是几号玩家？你的身份是什么？用一句话回答。"}
    ],
    temperature=0.7
)

print("API 调用成功！")
print("回复：", response.choices[0].message.content)
