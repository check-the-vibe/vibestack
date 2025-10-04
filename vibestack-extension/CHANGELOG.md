# Changelog

## [0.1.0] - 2025-01-04

### Added
- Complete Vibestack API integration
- Session management UI (create, list, switch)
- Real-time log polling (1-second refresh)
- Command execution via REST API
- Configurable API endpoint
- Session persistence in Chrome storage

### Changed
- Renamed from "AgentDriver" to "vibestack-chrome-extension"
- Updated all branding and UI text
- Modified terminal overlay to use Vibestack API instead of OpenAI
- Default API URL: `https://afeeb1ba4000.ngrok.app`
- API paths use nginx proxy: `/admin/api/...`

### API Endpoints
- `GET /admin/api/sessions` - List all sessions
- `POST /admin/api/sessions` - Create new session
- `POST /admin/api/sessions/{name}/input` - Send commands
- `GET /admin/api/sessions/{name}/log?lines=500` - Fetch logs

### Fixed
- Corrected API URL construction to use `/admin/api/` prefix
- Updated all fetch calls to use proper nginx proxy paths
