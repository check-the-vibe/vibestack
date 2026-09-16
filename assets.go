package vibestackassets

import "embed"

// Files are the secret-free, version-matched bootstrap and agent references
// served by the host runner.  Credentials and instance state are never assets.
//
//go:embed api/runner.openapi.json cli.sh docs/CLI.md docs/AUTOMATION.md docs/RUNNER.md runtime/AGENTS.md skills/vibestack/SKILL.md skills/vibestack/references/*.md
var Files embed.FS
