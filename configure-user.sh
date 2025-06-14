#!/bin/bash

# User Configuration Script for Docker Container
# This script configures git and API keys based on environment variables

set -e

echo "🔧 Configuring user environment..."

# Git Configuration
if [ -n "$GIT_USER_NAME" ] && [ -n "$GIT_USER_EMAIL" ]; then
    echo "📝 Setting up git configuration..."
    su - vnc -c "git config --global user.name \"$GIT_USER_NAME\""
    su - vnc -c "git config --global user.email \"$GIT_USER_EMAIL\""
    echo "✅ Git configured for $GIT_USER_NAME ($GIT_USER_EMAIL)"
else
    echo "⚠️  Git configuration skipped - GIT_USER_NAME and/or GIT_USER_EMAIL not provided"
fi

# API Key Configuration
API_KEYS_SET=0

# OpenAI API Key
if [ -n "$OPENAI_API_KEY" ]; then
    echo "🔑 Setting up OpenAI API key..."
    su - vnc -c "echo 'export OPENAI_API_KEY=\"$OPENAI_API_KEY\"' >> ~/.bashrc"
    API_KEYS_SET=1
    echo "✅ OpenAI API key configured"
fi

# Anthropic API Key
if [ -n "$ANTHROPIC_API_KEY" ]; then
    echo "🔑 Setting up Anthropic API key..."
    su - vnc -c "echo 'export ANTHROPIC_API_KEY=\"$ANTHROPIC_API_KEY\"' >> ~/.bashrc"
    API_KEYS_SET=1
    echo "✅ Anthropic API key configured"
fi

if [ $API_KEYS_SET -eq 0 ]; then
    echo "⚠️  No API keys configured - OPENAI_API_KEY and ANTHROPIC_API_KEY not provided"
fi

# Additional LLM CLI configuration
if [ -n "$OPENAI_API_KEY" ]; then
    su - vnc -c "llm keys set openai \"$OPENAI_API_KEY\"" 2>/dev/null || echo "⚠️  LLM CLI OpenAI key setup failed (this is optional)"
fi

echo "🎉 User configuration complete!"