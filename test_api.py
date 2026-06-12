import os
from openai import OpenAI

client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

response = client.chat.completions.create(
    model="qwen-plus",
    messages=[
        {"role": "system", "content": "你是一个狼人杀玩家，身份是狼人。"},
        {"role": "user", "content": "你是几号玩家？你的身份是什么？用一句话回答。"}
    ],
    temperature=0.7
)

print("API 调用成功！")
print("回复：", response.choices[0].message.content)
