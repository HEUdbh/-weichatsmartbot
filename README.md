WeChat DeepSeek 智能助手使用说明

[版本说明]
- main分支中为python源代码，仅供参考。
- release分支中为打包好的可执行程序

[界面说明]
1. 左侧控制面板: 管理监听对象和控制监听状态
2. 右侧日志区域: 实时显示程序运行状态
3. 状态指示器: 顶部右侧显示当前运行状态
4. 状态栏: 底部显示详细信息和版本

[使用步骤]
1. 添加监听对象: 点击"添加联系人"按钮
2. 启动监听: 点击"开始监听"按钮
3. 查看日志: 右侧区域实时显示运行状态
4. 停止监听: 点击"停止监听"按钮

[注意事项]
- 保持微信客户端处于登录状态
- 程序需要访问DeepSeek API，确保网络畅通
- Deepseek可能出现服务器繁忙的情况，程序会自动重试5次，之后将不再对超时的信息进行恢复。

[API密钥获取]
- 访问https://platform.deepseek.com/
- 左侧选择API Key进入后创建密钥（需要在首页充值）
- 将生成的密钥输入程序中的API处用于后续程序对API的调用
