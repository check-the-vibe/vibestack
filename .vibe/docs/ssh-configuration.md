# SSH Configuration

The Docker container now includes SSH server support for remote access.

## SSH Access Details
- SSH port: 22 (exposed in Docker)
- Root user: `root` with password `root`
- VNC user: `vnc` with password `vnc`

## To connect via SSH
```bash
ssh vnc@<container-ip>
# or as root
ssh root@<container-ip>
```

## Security Notes
- For production use, consider:
  - Changing default passwords
  - Using SSH keys instead of passwords
  - Restricting SSH access to specific users