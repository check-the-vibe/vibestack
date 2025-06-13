# User Configuration Guide

This Docker container supports automatic configuration of git settings and API keys through environment variables.

## Quick Start

### Option 1: Using docker-compose (Recommended)

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` with your information:
   ```bash
   # Required for git operations
   GIT_USER_NAME=John Doe
   GIT_USER_EMAIL=john.doe@example.com
   
   # Optional API keys for LLM integrations
   OPENAI_API_KEY=sk-your-openai-api-key-here
   ANTHROPIC_API_KEY=sk-ant-your-anthropic-api-key-here
   ```

3. Start the container:
   ```bash
   docker-compose up -d
   ```

### Option 2: Using docker run

```bash
docker run -d \
  -p 6080:6080 \
  -p 2222:22 \
  -e GIT_USER_NAME="John Doe" \
  -e GIT_USER_EMAIL="john.doe@example.com" \
  -e OPENAI_API_KEY="sk-your-openai-api-key-here" \
  -e ANTHROPIC_API_KEY="sk-ant-your-anthropic-api-key-here" \
  -v $(pwd)/mnt:/home/vnc/mnt \
  your-container-name
```

## Environment Variables

### Required for Git Operations
- `GIT_USER_NAME`: Your full name for git commits
- `GIT_USER_EMAIL`: Your email address for git commits

### Optional for LLM Integrations
- `OPENAI_API_KEY`: Your OpenAI API key for GPT models
- `ANTHROPIC_API_KEY`: Your Anthropic API key for Claude models

### Container Configuration (Optional)
- `NOVNC_PORT`: noVNC web interface port (default: 6080)
- `VNC_PORT`: VNC server port (default: 5900)
- `RESOLUTION`: Display resolution (default: 1280x720)
- `VNC_PASSWORD`: VNC password (default: no password)

## Configuration Process

The container automatically runs a configuration script on first startup that:

1. ✅ Sets up git user name and email globally
2. ✅ Configures API keys in the user's bash environment
3. ✅ Sets up LLM CLI with OpenAI key (if provided)
4. ✅ Creates a configuration marker to prevent re-running

## Accessing the Container

- **Web Interface**: http://localhost:6080
- **SSH Access**: `ssh vnc@localhost -p 2222` (password: vnc)
- **Direct Shell**: `docker exec -it container_name bash`

## Security Notes

- API keys are stored in the user's `.bashrc` file
- SSH is enabled with password authentication
- Consider using SSH keys for production environments
- API keys are only visible to the `vnc` user inside the container

## Troubleshooting

If configuration doesn't work:

1. Check if environment variables are set:
   ```bash
   docker exec container_name env | grep -E "(GIT_|API_KEY)"
   ```

2. Manually run configuration:
   ```bash
   docker exec container_name /configure-user.sh
   ```

3. Check configuration status:
   ```bash
   docker exec -u vnc container_name git config --global --list
   ```