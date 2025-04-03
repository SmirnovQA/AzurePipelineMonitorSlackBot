# AzurePipelineMonitorSlackBot
Bot will check Azure pipelines if they're enabled, disabled or paused. Use [/] commands /pipeline-status 'list' [to show monotored pipelines], 'add' 'delete' &lt;ID> [add/delete pipelines from list], 'toggle &lt;ID> [to enable paused/disabled pipeline or pause pipeline]

## Few important notes
When you're adding slash [/] command for your Skack app, format **MUST** be https://[your_url]/**slack/events**/[command]
Check API_VERSION for your Azure environment
"queueStatus": enabled/disabled/paused, **NOT** 0,1,2 like in a response on a web page
