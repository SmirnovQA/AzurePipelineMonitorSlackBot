from flask import Flask, request, Response
import os
import requests
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.signature import SignatureVerifier
import json
import base64
import logging


app = Flask(__name__)

# Configuration
load_dotenv()
BOT_TOKEN = os.getenv('SLACK_BOT_TOKEN') # Replace with your Slack Bot User OAuth Token
AZURE_ORG = os.getenv("AZURE_ORG") # Replace with your Azure DevOps organization
AZURE_PROJECT = os.getenv("AZURE_PROJECT") # Replace with your project name
AZURE_PROJECT_ID = os.getenv("AZURE_PROJECT_ID") # Replace with your Azure DevOps project ID (GUID)
AZURE_PAT_TOKEN = os.getenv("AZURE_PAT")  # Replace with your Azure DevOps PAT
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET") # Replace with your Slack Signing Secret
CHANNEL_PIPELINES_PATH = os.getenv("PIPELINE_STORAGE_PATH", "monitored_pipelines.json") # Default to local file
DEFAULT_SLACK_CHANNEL_NAME = os.getenv("SLACK_CHANNEL")

API_VERSION = "?api-version=6.0" # Azure DevOps API version

# Logging configuration ENCODING PAT
print(f"Raw AZURE_PAT: '{AZURE_PAT_TOKEN}'")
PAT_ENCODED = base64.b64encode(f":{AZURE_PAT_TOKEN}".encode()).decode()
print(f"Encoded PAT: '{PAT_ENCODED}'")

# Initialize Slack client
slack_client = WebClient(token=BOT_TOKEN)

# Get default channel ID dynamically on startup
def get_channel_id(channel_name):
    try:
        result = slack_client.conversations_list()
        for channel in result["channels"]:
            if channel["name"] == channel_name.lstrip("#"):
                return channel["id"]
    except Exception as e:
        logging.error(f"Failed to fetch channel ID for {channel_name}: {str(e)}")
    return None  # Fallback if not found

DEFAULT_SLACK_CHANNEL_ID = get_channel_id(DEFAULT_SLACK_CHANNEL_NAME) or "C_DEFAULT_FALLBACK"  # Replace with actual ID if known


def load_channel_pipelines():
    print(f"Looking for file at: {CHANNEL_PIPELINES_PATH}")
    print(f"File exists: {os.path.exists(CHANNEL_PIPELINES_PATH)}")
    # Load monitored pipelines from a JSON file, or return default list if file doesn't exist
    try:
        with open(CHANNEL_PIPELINES_PATH, 'r') as f:
            data = json.load(f)
            logging.debug(f"Loaded raw data from {CHANNEL_PIPELINES_PATH}: {data}")
            if isinstance(data, list):  # Handle old list format
                logging.warning("Found list instead of dict, converting to default channel")
                return {DEFAULT_SLACK_CHANNEL_ID: [int(pid) for pid in data]}
            elif not isinstance(data, dict):
                logging.error("Invalid data format, resetting to default")
                return {DEFAULT_SLACK_CHANNEL_ID: [123, 1234]} # Default monitored pipelines
            # Convert channel names to IDs and ensure pipeline IDs are int
            corrected_data = {}
            for channel, pids in data.items():
                if channel.startswith("#"):
                    channel_id = get_channel_id(channel) or DEFAULT_SLACK_CHANNEL_ID
                else:
                    channel_id = channel  # Assume it's already an ID
                corrected_data[channel_id] = [int(pid) for pid in pids]
            return corrected_data
    except (FileNotFoundError, json.JSONDecodeError):
        {DEFAULT_SLACK_CHANNEL_ID: [123, 1234]}  # Default monitored pipelines if file not found or invalid JSON

def save_channel_pipelines():
    with open(CHANNEL_PIPELINES_PATH, 'w') as f:
        json.dump(CHANNEL_PIPELINES, f)
# Load the monitored pipelines list at startup
CHANNEL_PIPELINES = load_channel_pipelines()
# Slack signature verifier

verifier = SignatureVerifier(SLACK_SIGNING_SECRET)

# Azure DevOps API headers
HEADERS = {
    "Content-Type": "application/json; charset=utf-8; api-version=6.0-preview.7",
    "Authorization": f"Basic {PAT_ENCODED}",
    "Accept": "application/json"
}

def get_pipeline_status(pipeline_id):
    # Fetch pipeline status from Azure DevOps API
    url = f"https://{AZURE_ORG}.visualstudio.com/{AZURE_PROJECT_ID}/_apis/build/definitions/{pipeline_id}{API_VERSION}"
    print(f"Fetching: {url}")
    print(f"Headers: {HEADERS}")
    
    response = requests.get(url, headers=HEADERS)
    print(f"Response: {response.status_code} - {response.text}")
    
    if response.status_code != 200:
        return None, None, f"Error: Could not fetch pipeline {pipeline_id}. Status code: {response.status_code}"
    
    pipeline_data = response.json()
    pipeline_name = pipeline_data["name"]
    queue_status = pipeline_data["queueStatus"]
    print(f"Raw queueStatus: {queue_status} (type: {type(queue_status)})")
    status = "enabled" if queue_status == "enabled" else "paused" if queue_status == "paused" else "disabled"
    # Emojis based messages on status
    if status == "enabled":
        status_message = f":white_check_mark: Pipeline '{pipeline_name}' (ID: {pipeline_id}) is *{status}* :white_check_mark:"
    elif status == "disabled":
        status_message = f":x: Pipeline '{pipeline_name}' (ID: {pipeline_id}) is *{status}* :x:"
    elif status == "paused":
        status_message = f":double_vertical_bar: Pipeline '{pipeline_name}' (ID: {pipeline_id}) is *{status}* :double_vertical_bar:"
    return pipeline_name, queue_status, status_message

def get_pipeline_name(pipeline_id):
    pipeline_name, _, _ = get_pipeline_status(pipeline_id)
    return pipeline_name if pipeline_name else str(pipeline_id)  # Fallback to ID if fetch fails

def toggle_pipeline_status(pipeline_id, current_status):
    """Toggle pipeline status based on current state:
    - Enabled (0) -> Paused (1)
    - Paused (1) -> Enabled (0)
    - Disabled (2) -> Enabled (0)"""
    url = f"https://{AZURE_ORG}.visualstudio.com/{AZURE_PROJECT_ID}/_apis/build/definitions/{pipeline_id}{API_VERSION}"
    
    # Fetch current pipeline definition
    response = requests.get(url, headers=HEADERS)
    if response.status_code != 200:
        return f"Error: Could not fetch pipeline {pipeline_id} for update. Status code: {response.status_code}"
    
    pipeline_data = response.json()
    pipeline_name = pipeline_data["name"]
    
    # Determine new status based on current queueStatus
    if current_status == "enabled":  # Enabled -> Paused
        new_status = "paused"
        status_text = "paused"
    elif current_status == "paused":  # Paused -> Enabled
        new_status = "enabled"
        status_text = "enabled"
    elif current_status == "disabled":  # Disabled -> Enabled
        new_status = "enabled"
        status_text = "enabled"
    else:
        return f"Error: Unknown queueStatus {current_status} for pipeline {pipeline_id}"

    pipeline_data["queueStatus"] = new_status
    
    # Update pipeline status
    update_response = requests.put(url, headers=HEADERS, data=json.dumps(pipeline_data))
    
    
    if update_response.status_code == 200:
        if status_text == "enabled":
            return f":white_check_mark: Pipeline '{pipeline_name}' (ID: {pipeline_id}) has been *{status_text}* :white_check_mark:"
        elif status_text == "paused":
            return f":double_vertical_bar: Pipeline '{pipeline_name}' (ID: {pipeline_id}) has been *{status_text}* :double_vertical_bar:"
    else:
        return f"Error: Failed to update pipeline {pipeline_id}. Status code: {update_response.status_code}"

def add_monitored_pipeline(channel_id, pipeline_id):
    # Add a pipeline ID to the monitored list and save to file
    pipeline_id = int(pipeline_id)
    if channel_id not in CHANNEL_PIPELINES:
        CHANNEL_PIPELINES[channel_id] = []
    if pipeline_id in CHANNEL_PIPELINES[channel_id]:
        return f"Pipeline ID {pipeline_id} is already in the monitored list for this channel."
    pipeline_name, _, status_message = get_pipeline_status(pipeline_id)
    if pipeline_name:
        CHANNEL_PIPELINES[channel_id].append(pipeline_id)
        save_channel_pipelines()
        pipeline_list = [f"{pid} ({get_pipeline_name(pid)})" for pid in CHANNEL_PIPELINES[channel_id]]
        return f"Added pipeline '{pipeline_name}' (ID: {pipeline_id}) to monitored list.\nCurrent monitored pipelines: {', '.join(pipeline_list)}"
    return status_message

def delete_monitored_pipeline(channel_id, pipeline_id):
    # Remove a pipeline ID from the monitored list and save to file
    pipeline_id = int( pipeline_id)
    if channel_id in CHANNEL_PIPELINES and pipeline_id in CHANNEL_PIPELINES[channel_id]:
        CHANNEL_PIPELINES[channel_id].remove(pipeline_id)
        if not CHANNEL_PIPELINES[channel_id]:
            del CHANNEL_PIPELINES[channel_id]
        save_channel_pipelines()
        pipeline_list = [f"{pid} ({get_pipeline_name(pid)})" for pid in CHANNEL_PIPELINES.get(channel_id, [])] if CHANNEL_PIPELINES.get(channel_id) else ["None"]
        return f"Removed pipeline ID {pipeline_id} from monitored list.\nCurrent monitored pipelines: {', '.join(pipeline_list)}"
    return f"Pipeline ID {pipeline_id} is not in the monitored list for this channel."

def list_monitored_pipelines(channel_id):
   # List all monitored pipelines with their status
    if channel_id not in CHANNEL_PIPELINES or not CHANNEL_PIPELINES[channel_id]:
        return "No pipelines are currently monitored in this channel."
    response_lines = []
    for pipeline_id in CHANNEL_PIPELINES[channel_id]:
        _, _, status_message = get_pipeline_status(pipeline_id)
        response_lines.append(status_message)
    return "\n".join(response_lines)

@app.route("/slack/events/pipeline-status", methods=["POST"])
def pipeline_status():
    # Handle Slack slash command
    print(f"Received request: {request.path} with data: {request.form}")
    # Uncomment for production next 2 lines
    #if not verifier.is_valid_request(request.get_data(), request.headers):
        #return Response("Invalid request", status=403) 
    # Extract command text and channel ID from the request
    channel_id = request.form.get("channel_id", DEFAULT_SLACK_CHANNEL_ID)
    command_text = request.form.get("text", "").strip().split()
    
    if not command_text:
        response ={"response_type": "in_channel", "text": "Please provide a command (e.g., /pipeline-status list, /pipeline-status add [id], /pipeline-status delete [id], /pipeline-status toggle [id])"}
        return Response(json.dumps(response), mimetype="application/json", status=200)
    # Command: /pipeline-status add <pipeline_id>
    if command_text[0].lower() == "add":
        if len(command_text) < 2 or not command_text[1].isdigit():
            return Response({"response_type": "in_channel", "text": "Please provide a valid pipeline ID (e.g., /pipeline-status add 123)"}, status=200)
        pipeline_id = command_text[1]
        response_text = add_monitored_pipeline(channel_id, pipeline_id)
        response = {"response_type": "in_channel", "text": response_text}
        return Response(json.dumps(response), mimetype="application/json", status=200)

    # Command: /pipeline-status delete <pipeline_id>
    if command_text[0].lower() == "delete":
        if len(command_text) < 2 or not command_text[1].isdigit():
            return Response({"response_type": "in_channel", "text": "Please provide a valid pipeline ID (e.g., /pipeline-status delete 123)"}, status=200)
        pipeline_id = command_text[1]
        response_text = delete_monitored_pipeline(channel_id, pipeline_id)
        response = {"response_type": "in_channel", "text": response_text}
        return Response(json.dumps(response), mimetype="application/json", status=200)

    # Command: /pipeline-status list
    if command_text[0].lower() == "list":
        response_text = list_monitored_pipelines(channel_id)
        response = {"response_type": "in_channel", "text": response_text}
        return Response(json.dumps(response), mimetype="application/json", status=200)

    # Command: /pipeline-status <id1> <id2> ... [toggle]
    pipeline_ids = [pid for pid in command_text if pid.isdigit()]
    toggle = "toggle" in [arg.lower() for arg in command_text]
    
    if not pipeline_ids:
        response = {"response_type": "in_channel", "text": "Please provide valid pipeline IDs (e.g., /pipeline-status [toggle] 123)"}
        return Response(json.dumps(response), mimetype="application/json", status=200)
    
    response_lines = []
    for pipeline_id in pipeline_ids:
        pipeline_name, queue_status, status_message = get_pipeline_status(pipeline_id)
        
        if pipeline_name is None:
            response_lines.append(status_message)
            continue
        
        response_lines.append(status_message)
        
        if toggle:
            toggle_result = toggle_pipeline_status(pipeline_id, queue_status)
            response_lines.append(toggle_result)
    
    response_text = "\n".join(response_lines)
    response = {"response_type": "in_channel", "text": response_text}
    return Response(json.dumps(response), mimetype="application/json", status=200)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80, debug=True)