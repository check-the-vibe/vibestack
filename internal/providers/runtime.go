package providers

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"unicode/utf8"
)

var (
	ErrUnavailable = errors.New("provider is unavailable")
	ErrUnsupported = errors.New("provider action is unsupported")
	ErrConflict    = errors.New("inspect the existing provider operation before retrying")
	ErrInvalid     = errors.New("invalid provider input")
)

// Model is a reviewed projection, never a provider configuration object (which
// can contain credentials). Availability is not proof of account or quota access.
type Model struct {
	ID      string `json:"id"`
	Name    string `json:"name"`
	Default bool   `json:"default"`
}

type RuntimeStatus struct {
	Authentication string  `json:"authentication"`
	Models         []Model `json:"models"`
}

// nativeEvent is private to the manager. Native approval handles never appear
// in the public event stream; the manager binds its own handle to an exact turn.
type nativeEvent struct {
	session, turn, item, kind, text, outcome string
	approval                                 json.RawMessage
	denyOnly, filePreview                    bool
}

type agentRuntime interface {
	Status(context.Context) (RuntimeStatus, error)
	Create(context.Context, string, string) (string, error)
	Resume(context.Context, string, string, string) error
	Submit(context.Context, string, string, string, string) (string, error)
	Interrupt(context.Context, string, string) error
	Approve(context.Context, json.RawMessage, bool) error
	Events() <-chan nativeEvent
	Close()
}

func boundedText(value string, limit int) string {
	value = strings.ToValidUTF8(value, "�")
	if len(value) <= limit {
		return value
	}
	value = value[:limit]
	for !utf8.ValidString(value) {
		value = value[:len(value)-1]
	}
	return value + "… [truncated]"
}

func nativeID(value string) bool {
	return len(value) > 0 && len(value) <= 256 && utf8.ValidString(value) && !strings.ContainsAny(value, "\x00\r\n")
}
