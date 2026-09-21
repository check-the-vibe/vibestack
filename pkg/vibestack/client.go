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
		Timeout:   65 * time.Second,
		Transport: transport,
		CheckRedirect: func(req *http.Request, via []*http.Request) error {
			if len(via) >= 5 {
				return errors.New("too many redirects")
			}
			if len(via) > 0 && !sameOrigin(via[0].URL, req.URL) {
				return http.ErrUseLastResponse
			}
			return nil
		},
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
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		defer resp.Body.Close()
		limited, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
		payload := struct {
			Code      string `json:"code"`
			Message   string `json:"message"`
			Error     string `json:"error"`
			RequestID string `json:"request_id"`
		}{}
		_ = json.Unmarshal(limited, &payload)
		message := payload.Message
		if message == "" {
			message = payload.Error
		}
		if message == "" {
			message = http.StatusText(resp.StatusCode)
		}
		requestID := resp.Header.Get("X-Request-ID")
		if payload.RequestID != "" {
			requestID = payload.RequestID
		}
		return nil, &HTTPError{Status: resp.StatusCode, Code: payload.Code, Message: message, RequestID: requestID}
	}
	return resp, nil
}

func (c *Client) JSON(ctx context.Context, method, relative string, input any, output any, authenticated bool, headers map[string]string) (string, error) {
	var body io.Reader
	if input != nil {
		encoded, err := json.Marshal(input)
		if err != nil {
			return "", err
		}
		body = bytes.NewReader(encoded)
	}
	resp, err := c.Do(ctx, method, relative, body, "application/json", authenticated, headers)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	data, readErr := io.ReadAll(io.LimitReader(resp.Body, (16<<20)+1))
	if readErr != nil {
		return resp.Header.Get("X-Request-ID"), readErr
	}
	if len(data) > 16<<20 {
		return resp.Header.Get("X-Request-ID"), errors.New("JSON response exceeds 16 MiB")
	}
	if output != nil {
		if err := json.Unmarshal(data, output); err != nil {
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
