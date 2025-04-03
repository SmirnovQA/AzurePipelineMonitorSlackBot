# AzurePipelineMonitorSlackBot
Bot will check Azure pipelines if they're enabled, disabled or paused. Use [/] commands /pipeline-status 'list' [to show monotored pipelines], 'add' 'delete' &lt;ID> [add/delete pipelines from list], 'toggle &lt;ID> [to enable paused/disabled pipeline or pause pipeline]  

[!TIP]
**Bot** can be added to any channel just by calling @[name] and also can operate in direct messages
Currently messages visible for everyone in a channel  
Remove * *"response_type": "in_channel"* * in line 212 and others to make it visible only for you

[!NOTE]
## Few important notes  
When you're adding slash [/] command for your Skack app, format **MUST** be https://[your_url]/**slack/events**/[command]  
Check API_VERSION for your Azure environment  
"queueStatus": enabled/disabled/paused, **NOT** 0,1,2 like in a response on a web page  
