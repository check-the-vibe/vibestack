package vibestack

import "encoding/json"

const (
	Version       = "0.2.0"
	WorkspaceAPI  = "/api/v1/automation"
	RunnerAPI     = "/api/v1/runner"
	DiscoveryPath = "/.well-known/vibestack"
)

type Discovery struct {
	Kind          string            `json:"kind"`
	Identity      string            `json:"identity"`
	Version       string            `json:"version"`
	APIVersions   []string          `json:"api_versions"`
	APIRoots      map[string]string `json:"api_roots"`
	Documentation map[string]string `json:"documentation"`
	Pairing       struct {
		Request     string   `json:"request"`
		Approval    string   `json:"approval"`
		Permissions []string `json:"permissions"`
	} `json:"pairing"`
}

type PairingRequest struct {
	PairingID        string `json:"pairing_id"`
	VerificationCode string `json:"verification_code"`
	PollingSecret    string `json:"polling_secret"`
	ExpiresAt        string `json:"expires_at"`
	IntervalSeconds  int    `json:"interval_seconds"`
}

type PairingResult struct {
	Status      string   `json:"status"`
	ClientID    string   `json:"client_id,omitempty"`
	Credential  string   `json:"credential,omitempty"`
	Permissions []string `json:"permissions,omitempty"`
	ExpiresAt   string   `json:"expires_at,omitempty"`
}

type Job struct {
	ID              string `json:"id"`
	Kind            string `json:"kind"`
	Status          string `json:"status"`
	ExitCode        *int   `json:"exit_code"`
	ErrorCode       string `json:"error_code,omitempty"`
	StdoutBytes     int64  `json:"stdout_bytes"`
	StderrBytes     int64  `json:"stderr_bytes"`
	StdoutTruncated bool   `json:"stdout_truncated"`
	StderrTruncated bool   `json:"stderr_truncated"`
	CreatedAt       string `json:"created_at"`
	StartedAt       string `json:"started_at,omitempty"`
	FinishedAt      string `json:"finished_at,omitempty"`
}

type JobEnvelope struct {
	Job Job `json:"job"`
}

type OutputPage struct {
	JobID      string `json:"job_id"`
	Stream     string `json:"stream"`
	Data       string `json:"data"`
	Encoding   string `json:"encoding"`
	Cursor     int64  `json:"cursor"`
	NextCursor int64  `json:"next_cursor"`
	EOF        bool   `json:"eof"`
	Truncated  bool   `json:"truncated"`
}

type Instance struct {
	ID                   string            `json:"id"`
	Name                 string            `json:"name"`
	Owner                string            `json:"owner"`
	Template             string            `json:"template"`
	ImageDigest          string            `json:"image_digest"`
	ContainerID          string            `json:"container_id,omitempty"`
	DesiredState         string            `json:"desired_state"`
	ObservedState        string            `json:"observed_state"`
	Ready                bool              `json:"ready"`
	InfrastructureReady  bool              `json:"infrastructure_ready"`
	ApplicationsRestored bool              `json:"applications_restored"`
	Onboarding           bool              `json:"onboarding_required"`
	Connections          map[string]string `json:"connection_status"`
	Ports                map[string]int    `json:"ports"`
	URLs                 map[string]string `json:"urls"`
	CreatedAt            string            `json:"created_at"`
	UpdatedAt            string            `json:"updated_at"`
	LastError            string            `json:"last_safe_error,omitempty"`
}

type Operation struct {
	ID             string          `json:"id"`
	InstanceID     string          `json:"instance_id,omitempty"`
	Kind           string          `json:"kind"`
	Status         string          `json:"status"`
	IdempotencyKey string          `json:"idempotency_key,omitempty"`
	RequestID      string          `json:"request_id,omitempty"`
	ErrorCode      string          `json:"error_code,omitempty"`
	ErrorMessage   string          `json:"error_message,omitempty"`
	Result         json.RawMessage `json:"result,omitempty"`
	CreatedAt      string          `json:"created_at"`
	UpdatedAt      string          `json:"updated_at"`
}
