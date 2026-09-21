package vibestack

import (
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

type HTTPError struct {
	Status    int
	Code      string
	Message   string
	RequestID string
	Retryable bool
}

func (e *HTTPError) Error() string {
	if e.RequestID != "" {
		return fmt.Sprintf("%s (HTTP %d, request %s)", e.Message, e.Status, e.RequestID)
	}
	return fmt.Sprintf("%s (HTTP %d)", e.Message, e.Status)
}

type Client struct {
	AuthenticationMode string
	InstanceID         string
	ExpectedIdentity   string
	GatewayTokenFile   string
	Base               *url.URL
	Credential         string
	HTTP               *http.Client
}

func NewClient(rawURL, credential, caFile string) (*Client, error) {
	base, err := url.Parse(rawURL)
	if err != nil || base.Scheme == "" || base.Host == "" || base.User != nil || base.RawQuery != "" || base.Fragment != "" {
		return nil, errors.New("server URL must be an absolute HTTP(S) origin")
	}
	base.Path = strings.TrimSuffix(base.EscapedPath(), "/")
	if base.Path != "" {
		return nil, errors.New("server URL must not contain a path; reverse-proxy subpaths are not supported")
	}
	if base.Scheme != "https" {
		host := strings.Trim(base.Hostname(), "[]")
		if base.Scheme != "http" || (host != "localhost" && net.ParseIP(host) == nil) || (host != "localhost" && !net.ParseIP(host).IsLoopback()) {
			return nil, errors.New("HTTP is allowed only for loopback development")
		}
	}
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.TLSClientConfig = &tls.Config{MinVersion: tls.VersionTLS12}
	if caFile != "" {
		pem, readErr := os.ReadFile(caFile)
		if readErr != nil {
			return nil, fmt.Errorf("read custom CA: %w", readErr)
		}
		pool, poolErr := x509.SystemCertPool()
		if poolErr != nil || pool == nil {
			pool = x509.NewCertPool()
		}
		if !pool.AppendCertsFromPEM(pem) {
			return nil, errors.New("custom CA contains no certificates")
		}
		transport.TLSClientConfig.RootCAs = pool
	}
	httpClient := &http.Client{
		Timeout:       65 * time.Second,
		Transport:     transport,
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	}
	return &Client{Base: base, Credential: credential, HTTP: httpClient}, nil
}

func sameOrigin(a, b *url.URL) bool {
	return strings.EqualFold(a.Scheme, b.Scheme) && strings.EqualFold(a.Host, b.Host)
}

func (c *Client) URL(relative string) (string, error) {
	if !strings.HasPrefix(relative, "/") || strings.HasPrefix(relative, "//") {
		return "", errors.New("API path must be a single-origin relative path")
	}
	reference, err := url.Parse(relative)
	if err != nil || reference.IsAbs() || reference.Host != "" {
		return "", errors.New("API path must be a valid relative path")
	}
	return c.Base.ResolveReference(reference).String(), nil
}

func (c *Client) Do(ctx context.Context, method, relative string, body io.Reader, contentType string, authenticated bool, headers map[string]string) (*http.Response, error) {
	if c.InstanceID != "" {
		if !(strings.HasPrefix(relative, WorkspaceAPI) || strings.HasPrefix(relative, "/api/v1/") || relative == "/setup/api/state") {
			return nil, errors.New("route is not available through workspace mediation")
		}
		relative = RunnerAPI + "/instances/" + url.PathEscape(c.InstanceID) + "/workspace" + relative
		authenticated = true
	}
	target, err := c.URL(relative)
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(ctx, method, target, body)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", "vibestack/"+Version)
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	if authenticated && c.AuthenticationMode != "trusted-tailnet" {
		if c.Credential == "" {
			return nil, errors.New("profile has no client credential")
		}
		req.Header.Set("Authorization", "Bearer "+c.Credential)
	}
	for name, value := range headers {
		req.Header.Set(name, value)
	}
	if authenticated && c.ExpectedIdentity != "" {
		if !bridgeIdentity.MatchString(c.ExpectedIdentity) || c.InstanceID != "" {
			return nil, errors.New("invalid workspace identity pin")
		}
		req.Header.Set("X-VibeStack-Expected-Instance", c.ExpectedIdentity)
	}
	if c.GatewayTokenFile != "" {
		if err := c.ValidateGateway(); err != nil {
			return nil, err
		}
		token, err := readGatewayCredential(c.GatewayTokenFile)
		if err != nil {
			return nil, err
		}
		req.Header.Set("X-GitHub-Token", token)
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		defer resp.Body.Close()
		limited, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
		payload := struct {
			Code      string          `json:"code"`
			Message   string          `json:"message"`
			Error     json.RawMessage `json:"error"`
			RequestID string          `json:"request_id"`
		}{}
		_ = json.Unmarshal(limited, &payload)
		message := payload.Message
		retryable := false
		if message == "" {
			var detail struct {
				Code      string `json:"code"`
				Message   string `json:"message"`
				Retryable bool   `json:"retryable"`
			}
			if json.Unmarshal(payload.Error, &detail) == nil && detail.Code != "" {
				payload.Code, message, retryable = detail.Code, detail.Message, detail.Retryable
			} else {
				_ = json.Unmarshal(payload.Error, &message)
			}
		}
		if message == "" {
			message = http.StatusText(resp.StatusCode)
		}
		requestID := resp.Header.Get("X-Request-ID")
		if payload.RequestID != "" {
			requestID = payload.RequestID
		}
		return nil, &HTTPError{Status: resp.StatusCode, Code: payload.Code, Message: message, RequestID: requestID, Retryable: retryable}
	}
	return resp, nil
}

// ValidateGateway allows only an explicitly configured private Codespaces origin.
// The credential is read from its protected file afresh for each request; no
// ambient environment credential or redirect can select another destination.
func (c *Client) ValidateGateway() error {
	if c.GatewayTokenFile != "" && (c.Base == nil || c.Base.Scheme != "https" || !strings.HasSuffix(strings.ToLower(c.Base.Hostname()), ".app.github.dev") || c.Base.Port() != "" && c.Base.Port() != "443") {
		return errors.New("a gateway credential requires an explicit HTTPS Codespaces forwarded origin")
	}
	return nil
}

func (c *Client) JSON(ctx context.Context, method, relative string, input any, output any, authenticated bool, headers map[string]string) (string, error) {
	var body io.Reader
	if input != nil {
		encoded, err := json.Marshal(input)
		if err != nil {
			return "", err
		}
		if len(encoded) > 24<<20 {
			return "", errors.New("JSON request exceeds 24 MiB")
		}
		body = bytes.NewReader(encoded)
	}
	resp, err := c.Do(ctx, method, relative, body, "application/json", authenticated, headers)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	data, readErr := io.ReadAll(io.LimitReader(resp.Body, (24<<20)+1))
	if readErr != nil {
		return resp.Header.Get("X-Request-ID"), readErr
	}
	if len(data) > 24<<20 {
		return resp.Header.Get("X-Request-ID"), errors.New("JSON response exceeds 24 MiB")
	}
	if output != nil {
		if !json.Valid(data) {
			return resp.Header.Get("X-Request-ID"), errors.New("response is not one JSON value; check the endpoint and gateway login")
		}
		decoder := json.NewDecoder(bytes.NewReader(data))
		decoder.UseNumber()
		if err := decoder.Decode(output); err != nil {
			return resp.Header.Get("X-Request-ID"), fmt.Errorf("decode response: %w", err)
		}
	}
	return resp.Header.Get("X-Request-ID"), nil
}

func (c *Client) Discover(ctx context.Context) (Discovery, error) {
	var value Discovery
	_, err := c.JSON(ctx, http.MethodGet, DiscoveryPath, nil, &value, false, nil)
	if err != nil {
		return Discovery{}, err
	}
	if value.Kind != "workspace" && value.Kind != "runner" {
		return Discovery{}, errors.New("server returned an unknown VibeStack kind")
	}
	if len(value.Identity) != 32 || !isLowerHex(value.Identity) || len(value.APIVersions) == 0 || len(value.APIVersions) > 16 {
		return Discovery{}, errors.New("server returned incomplete discovery metadata")
	}
	if c.ExpectedIdentity != "" && value.Identity != c.ExpectedIdentity {
		return Discovery{}, errors.New("server identity no longer matches the profile")
	}
	for _, version := range value.APIVersions {
		if version == "" || len(version) > 32 {
			return Discovery{}, errors.New("server returned invalid API versions")
		}
	}
	if value.AuthenticationMode == "" {
		value.AuthenticationMode = "paired"
	}
	if value.AuthenticationMode != "paired" && !(value.Kind == "runner" && value.AuthenticationMode == "trusted-tailnet") {
		return Discovery{}, errors.New("unsupported authentication mode")
	}
	return value, nil
}

func isLowerHex(value string) bool {
	for _, character := range value {
		if !(character >= '0' && character <= '9' || character >= 'a' && character <= 'f') {
			return false
		}
	}
	return true
}
