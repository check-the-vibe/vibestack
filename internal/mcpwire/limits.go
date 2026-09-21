// Package mcpwire holds wire bounds shared by the workspace HTTP adapter and
// its local stdio bridge. Operation policy stays in the capability registry.
package mcpwire

import "encoding/json"

const (
	FrameBytes = 24 << 20
	IDBytes    = 256
	// Reserve the bounded ID plus JSON-RPC fields around a serialized result.
	ResultBytes = FrameBytes - 512
)

// IDWithinLimit bounds the encoded JSON identifier without changing arguments.
// The SDK still owns protocol parsing and malformed-message errors.
func IDWithinLimit(frame []byte) bool {
	var header struct {
		ID json.RawMessage `json:"id"`
	}
	if json.Unmarshal(frame, &header) != nil {
		return true
	}
	if len(header.ID) > IDBytes {
		return false
	}
	// The SDK re-encodes string IDs. HTML and line-separator escaping can make
	// that representation larger than the caller's original JSON spelling.
	var id string
	if json.Unmarshal(header.ID, &id) == nil {
		encoded, _ := json.Marshal(id)
		return len(encoded) <= IDBytes
	}
	return true // the SDK validates non-string identifier types
}
