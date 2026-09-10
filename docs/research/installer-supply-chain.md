# Optional installer supply-chain policy

VibeStack installs large, fast-moving developer tools after the base image is
running. The setup catalog is therefore a separate supply-chain boundary from
the image build.

## Pinned runtime and command-line agents

Node.js is installed from the official `nodejs.org` binary archive, not by
executing a downloaded repository-bootstrap script as root. The installer pins
Node.js 22.23.2 and records separate SHA-256 digests for the upstream x64 and
arm64 tarballs. It permits HTTPS downloads and redirects only, stores the
archive in a root-owned `0700` temporary directory, verifies the digest, then
validates every tar member before extraction into a private staging directory.
The validator rejects paths outside the one expected archive root, duplicate
members, devices and FIFOs, set-id modes, and links that escape, cycle, traverse
a non-directory archive member, or become invalid after the extraction root is
removed by `--strip-components=1`. The staged and installed `node` and `npm`
versions must report `v22.23.2` and `10.9.8` respectively.

Extraction happens in a unique root-owned mode-`0700` sibling below
`/opt/vibestack`. A second filesystem-tree validation rejects wrong ownership,
writable or set-id entries, special files, mount crossings, escaping/dangling
symlinks, and hard links outside the tree. Only then is the complete tree
atomically renamed to `/opt/vibestack/node-v22.23.2-linux-{x64,arm64}`. An
existing tree is reused only after the same ownership, structure, and exact
runtime-version checks pass. Four stable command symlinks in `/usr/local/bin`
resolve through one atomically replaced `node-current` pointer; link publication
keeps no-follow backups and rolls back the pointer and commands if any step or
postcondition fails. Node installation never merges into `/usr/local/include`,
`lib`, `share`, or the generic documentation files.

The privileged installer also holds a non-blocking root-owned lock for the
whole dependency-ordered run. Each direct artifact has explicit connection,
wall-clock, and byte limits, and temporary cleanup accepts only the exact
root-owned private directory shapes created by the installer.

The npm requests for Claude Code, Codex CLI, and OpenCode use exact direct
package versions and verify each installed package manifest:

- `@anthropic-ai/claude-code@2.1.263`
- `@openai/codex@0.153.4`
- `opencode-ai@1.18.29`

An upgrade must change the version and reviewed hashes/specifications together,
then pass a disposable installation before live rollout.

## Pinned Godot editor

Godot uses the official standard Linux editor archives from the project's
[`4.7.2-stable` GitHub release](https://github.com/godotengine/godot/releases/tag/4.7.2-stable),
which the official [Godot release archive](https://godotengine.org/download/archive/)
identifies as the latest stable release. VibeStack supports the same two
64-bit architectures as the rest of its multi-architecture catalog:

| Architecture | Official archive | SHA-256 |
|---|---|---|
| amd64 / x86_64 | [`Godot_v4.7.2-stable_linux.x86_64.zip`](https://github.com/godotengine/godot/releases/download/4.7.2-stable/Godot_v4.7.2-stable_linux.x86_64.zip) | `cadd3204e728a35d3f13adb7fd0d7902636b79f6b95c40c265eb73b6c35329e4` |
| arm64 | [`Godot_v4.7.2-stable_linux.arm64.zip`](https://github.com/godotengine/godot/releases/download/4.7.2-stable/Godot_v4.7.2-stable_linux.arm64.zip) | `5dd0d86405cf7e8adf79fb6377b38ba682a2846cb378ffe5364f38c01ad29b9d` |

The installer downloads into its private bounded temporary directory, verifies
the selected digest, and accepts exactly one expected regular 64-bit
little-endian ELF with the matching machine architecture. It verifies the
reported stable version before and after publishing `/usr/local/bin/godot`.
The desktop launcher follows Godot's upstream desktop-entry identity while
selecting the Compatibility renderer and dummy audio for VibeStack. The .NET
editor and export templates are intentionally outside this component. The
installer invalidates its convergence marker before publication and atomically
recreates `/usr/local/bin/.vibestack-godot-4.7.2.complete` only after the binary,
desktop entry, desktop database, and shortcut succeed. A partial late failure
therefore cannot satisfy the catalog probe and is repaired by a retry.

## Architecture and remaining trust

Claude Desktop uses Anthropic's signed apt repository and verifies that its one
primary key fingerprint, parsed from GnuPG's machine-readable colon format,
exactly matches the reviewed value; a matching subkey is insufficient. GnuPG
uses a private ephemeral home inside the root-owned installer temporary
directory, rather than depending on or modifying root's default keyring. Its
repository advertises amd64 and arm64. The
Google Chrome and ChatGPT desktop package endpoints are amd64-only. Their
installers fail before making a network request on any other architecture, and
the setup catalog says so explicitly.
ChatGPT also depends on Chrome in the catalog because its authentication is an
external-browser OAuth flow. The installer records Chrome as XFCE's default and
as the explicit HTTP/HTTPS/HTML MIME handler, then removes the ChatGPT package's
generic HTTP/HTTPS associations while retaining its app-specific callback
scheme. It also replaces XFCE's direct-Chrome preferred-application helper with
one that goes through `vibestack-app`; MIME correctness alone is insufficient
because a cold direct Chrome launch lacks the container compatibility flags.

Two limitations remain visible rather than being presented as cryptographic
pinning:

- Chrome and ChatGPT are fetched from vendor-controlled moving `latest` URLs.
  The download is private, HTTPS-only, and structurally validated as a Debian
  archive, but its exact bytes are not pinned by VibeStack.
- Exact npm top-level versions still arrive through the npm registry and their
  archive signatures are not independently signature-verified by VibeStack.
  Upstream dependency resolution and package lifecycle scripts remain part of
  that trust boundary; version pinning prevents silent top-level upgrades, not
  compromise of a selected artifact or its transitive graph.

These are reasons to run optional installation only on a disposable candidate
first and to keep the setup interface on the private loopback/Tailscale boundary.

The pinned runtime artifact is published on the official
[Node.js v22.23.2 release page](https://nodejs.org/en/blog/release/v22.23.2),
with the complete upstream digest list in
[`SHASUMS256.txt`](https://nodejs.org/dist/v22.23.2/SHASUMS256.txt).
