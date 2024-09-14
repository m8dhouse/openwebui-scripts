#!/bin/bash

# Activate the virtual environment
cd /usr/openweb
source venv/bin/activate

# Set environment variables
export ENV=prod
export WEBUI_AUTH=true
export WEBUI_NAME=OpenWebUI
export OPENAI_API_KEY=<key>
export ENABLE_RAG_WEB_SEARCH=true
export RAG_WEB_SEARCH_ENGINE=duckduckgo
export ENABLE_OAUTH_SIGNUP=true
export OAUTH_MERGE_ACCOUNTS_BY_EMAIL=true
export GOOGLE_CLIENT_ID=<key>
export GOOGLE_CLIENT_SECRET=<key>
export ANTHROPIC_API_KEY=<key>
export ENABLE_ADMIN_CHAT_ACCESS=false
export ENABLE_LOGIN_FORM=false

cd /usr/openweb/venv
# Run the Python script
open-webui serve

# Deactivate the virtual environment (optional, as the script will terminate)
deactivate
