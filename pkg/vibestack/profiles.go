package vibestack

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"syscall"
)

type Profile struct {
	Name       string `json:"name"`
	URL        string `json:"url"`
	Kind       string `json:"kind"`
	Identity   string `json:"identity"`
	Credential string `json:"credential"`
	CAFile     string `json:"ca_file,omitempty"`
	ClientID   string `json:"client_id,omitempty"`
}

type ProfileFile struct {
	Version  int                `json:"version"`
	Profiles map[string]Profile `json:"profiles"`
}

func ConfigPath() (string, error) {
	if value := os.Getenv("VIBESTACK_CONFIG"); value != "" {
		return value, nil
	}
	dir, err := os.UserConfigDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(dir, "vibestack", "profiles.json"), nil
}

func LoadProfiles() (ProfileFile, error) {
	path, err := ConfigPath()
	if err != nil {
		return ProfileFile{}, err
	}
	info, statErr := os.Lstat(path)
	if errors.Is(statErr, os.ErrNotExist) {
		return ProfileFile{Version: 1, Profiles: map[string]Profile{}}, nil
	}
	if statErr != nil {
		return ProfileFile{}, statErr
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 || stat.Uid != uint32(os.Geteuid()) || info.Size() > 1<<20 {
		return ProfileFile{}, errors.New("profile file has unsafe ownership, type, permissions, or size")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return ProfileFile{}, err
	}
	var value ProfileFile
	if json.Unmarshal(data, &value) != nil || value.Version != 1 || value.Profiles == nil {
		return ProfileFile{}, errors.New("profile file is invalid")
	}
	return value, nil
}

func SaveProfiles(value ProfileFile) error {
	path, err := ConfigPath()
	if err != nil {
		return err
	}
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0700); err != nil {
		return err
	}
	info, err := os.Lstat(dir)
	stat, ok := infoSys(info, err)
	if !ok || !info.IsDir() || info.Mode().Perm()&0077 != 0 || stat.Uid != uint32(os.Geteuid()) {
		return errors.New("profile directory has unsafe type or permissions")
	}
	encoded, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	tmp, err := os.CreateTemp(dir, ".profiles-*")
	if err != nil {
		return err
	}
	tmpName := tmp.Name()
	defer os.Remove(tmpName)
	if err := tmp.Chmod(0600); err != nil {
		tmp.Close()
		return err
	}
	if _, err := tmp.Write(append(encoded, '\n')); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Sync(); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if err := os.Rename(tmpName, path); err != nil {
		return err
	}
	directory, err := os.Open(dir)
	if err != nil {
		return err
	}
	defer directory.Close()
	return directory.Sync()
}

func infoSys(info os.FileInfo, err error) (*syscall.Stat_t, bool) {
	if err != nil || info == nil {
		return nil, false
	}
	value, ok := info.Sys().(*syscall.Stat_t)
	return value, ok
}

func SelectProfile(name string, kind string) (Profile, error) {
	profiles, err := LoadProfiles()
	if err != nil {
		return Profile{}, err
	}
	if name != "" {
		profile, ok := profiles.Profiles[name]
		if !ok {
			return Profile{}, fmt.Errorf("profile %q does not exist", name)
		}
		if kind != "" && profile.Kind != kind {
			return Profile{}, fmt.Errorf("profile %q targets a %s, not a %s", name, profile.Kind, kind)
		}
		return profile, nil
	}
	var matches []Profile
	for _, profile := range profiles.Profiles {
		if kind == "" || profile.Kind == kind {
			matches = append(matches, profile)
		}
	}
	if len(matches) == 0 {
		return Profile{}, errors.New("no matching profile; run vibestack connect")
	}
	if len(matches) > 1 {
		return Profile{}, errors.New("several profiles match; select one explicitly with --profile")
	}
	return matches[0], nil
}

func ProfileNames(value ProfileFile) []string {
	names := make([]string, 0, len(value.Profiles))
	for name := range value.Profiles {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}
