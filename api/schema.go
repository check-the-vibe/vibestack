package api

import _ "embed"

// WorkspaceOpenAPI is the compatibility route authority used by the workspace
// service. New registered capabilities augment this document in their adapter.
//
//go:embed workspace.openapi.json
var WorkspaceOpenAPI []byte
