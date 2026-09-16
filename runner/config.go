package runner

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/url"
	"os"
	"path/filepath"
)

const APIRoot = "/api/v1/runner"

type Config struct {
	Listen                  string `json:"listen"`
	PublicURL               string `json:"public_url"`
	StateDir                string `json:"state_dir"`
	PortMin                 int    `json:"port_min"`
	PortMax                 int    `json:"port_max"`
	MaxInstances            int    `json:"max_instances"`
	ProvisioningConcurrency int    `json:"provisioning_concurrency"`
	MinFreeBytes            int64  `json:"min_free_bytes"`
	DefaultMemoryBytes      int64  `json:"default_memory_bytes"`
	DefaultNanoCPUs         int64  `json:"default_nano_cpus"`
	DefaultPIDs             int64  `json:"default_pids"`
	MaxMemoryBytes          int64  `json:"max_memory_bytes"`
	MaxNanoCPUs             int64  `json:"max_nano_cpus"`
	MaxPIDs                 int64  `json:"max_pids"`
	ManageTailscaleServe    bool   `json:"manage_tailscale_serve"`
}

func DefaultConfig() Config {
	return Config{
		Listen:                  "127.0.0.1:8079",
		PublicURL:               "http://127.0.0.1:8079",
		StateDir:                "/var/lib/vibestack-runner",
		PortMin:                 10080,
		PortMax:                 19999,
		MaxInstances:            8,
		ProvisioningConcurrency: 2,
		MinFreeBytes:            10 << 30,
		DefaultMemoryBytes:      8 << 30,
		DefaultNanoCPUs:         4_000_000_000,
		DefaultPIDs:             1024,
		MaxMemoryBytes:          16 << 30,
		MaxNanoCPUs:             8_000_000_000,
		MaxPIDs:                 2048,
	}
}

func LoadConfig(path string) (Config, error) {
	defaults := DefaultConfig()
	value := defaults
	data, err := os.ReadFile(path)
	if err != nil {
		return Config{}, err
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&value); err != nil {
		return Config{}, fmt.Errorf("decode runner config: %w", err)
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		if err == nil {
			return Config{}, errors.New("decode runner config: trailing JSON value")
		}
		return Config{}, fmt.Errorf("decode runner config: %w", err)
	}
	// Configs written by the first preview had defaults but no explicit maxima.
	if value.MaxMemoryBytes == 0 {
		value.MaxMemoryBytes = defaults.MaxMemoryBytes
	}
	if value.MaxNanoCPUs == 0 {
		value.MaxNanoCPUs = defaults.MaxNanoCPUs
	}
	if value.MaxPIDs == 0 {
		value.MaxPIDs = defaults.MaxPIDs
	}
	if err := value.Validate(); err != nil {
		return Config{}, err
	}
	return value, nil
}

func (c Config) Validate() error {
	host, port, err := net.SplitHostPort(c.Listen)
	if err != nil || port == "" {
		return errors.New("listen must be a host:port authority")
	}
	ip := net.ParseIP(host)
	if host != "localhost" && (ip == nil || !ip.IsLoopback()) {
		return errors.New("runner listen address must remain loopback")
	}
	public, err := url.Parse(c.PublicURL)
	if err != nil || public.Scheme == "" || public.Host == "" || public.User != nil || public.Path != "" || public.RawQuery != "" || public.Fragment != "" {
		return errors.New("public_url must be an HTTP(S) origin without a path")
	}
	if public.Scheme != "https" {
		host := public.Hostname()
		ip := net.ParseIP(host)
		if public.Scheme != "http" || (host != "localhost" && (ip == nil || !ip.IsLoopback())) {
			return errors.New("non-loopback public_url must use HTTPS")
		}
	}
	if c.ManageTailscaleServe && public.Scheme != "https" {
		return errors.New("managed Tailscale Serve requires an HTTPS public_url")
	}
	if !filepath.IsAbs(c.StateDir) || filepath.Clean(c.StateDir) != c.StateDir || c.StateDir == "/" {
		return errors.New("state_dir must be a dedicated absolute path")
	}
	if c.PortMin < 1024 || c.PortMax > 65535 || c.PortMin > c.PortMax || c.PortMax-c.PortMin < 32 {
		return errors.New("port range is invalid or too small")
	}
	if c.MaxInstances < 1 || c.MaxInstances > 256 || c.ProvisioningConcurrency < 1 || c.ProvisioningConcurrency > 16 {
		return errors.New("runner limits are invalid")
	}
	if c.MinFreeBytes < 0 || c.DefaultMemoryBytes < 512<<20 || c.DefaultNanoCPUs < 100_000_000 || c.DefaultPIDs < 128 || c.DefaultPIDs > 4096 {
		return errors.New("resource defaults are invalid")
	}
	if c.MaxMemoryBytes < c.DefaultMemoryBytes || c.MaxNanoCPUs < c.DefaultNanoCPUs || c.MaxPIDs < c.DefaultPIDs || c.MaxPIDs > 4096 {
		return errors.New("resource limits must be at least their defaults and remain bounded")
	}
	return nil
}

func WriteDefaultConfig(path string, stateDir string) error {
	value := DefaultConfig()
	if stateDir != "" {
		value.StateDir = stateDir
	}
	if err := value.Validate(); err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		return err
	}
	data, _ := json.MarshalIndent(value, "", "  ")
	return os.WriteFile(path, append(data, '\n'), 0640)
}
