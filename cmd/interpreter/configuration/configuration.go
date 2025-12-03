package configuration

import (
	_ "embed"
	"fmt"
	"image/color"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/bquenin/interpreter/internal/translate"
	"github.com/rs/zerolog/log"
	"github.com/spf13/viper"
)

const (
	ConfigName = "config"
)

//go:embed default.yml
var defaultConfiguration []byte

type Translator struct {
	To                string `mapstructure:"to"`
	API               string `mapstructure:"api"`
	AuthenticationKey string `mapstructure:"authentication-key"`
}

type Subs struct {
	Font       Font       `mapstructure:"font"`
	Background Background `mapstructure:"background"`
}

type Font struct {
	Color string `mapstructure:"color"`
	Size  int    `mapstructure:"size"`
}

type Background struct {
	Color   string `mapstructure:"color"`
	Opacity int    `mapstructure:"opacity"`
}

type Configuration struct {
	WindowTitle         string     `mapstructure:"window-title"`
	RefreshRate         string     `mapstructure:"refresh-rate"`
	ConfidenceThreshold float32    `mapstructure:"confidence-threshold"`
	Translator          Translator `mapstructure:"translator"`
	Subs                Subs       `mapstructure:"subs"`
	Debug               bool
}

func Read() (*Configuration, error) {
	executable, err := os.Executable()
	if err != nil {
		return nil, err
	}

	// Add matching environment variables - will take precedence over config files.
	viper.AutomaticEnv()
	viper.SetEnvKeyReplacer(strings.NewReplacer(".", "_", "-", "_"))
	viper.SetEnvPrefix("INTERPRETER")

	// Add default config file search paths in order of decreasing precedence.
	viper.AddConfigPath(filepath.Dir(executable))
	viper.AddConfigPath(".")
	viper.AddConfigPath("$HOME")
	viper.SetConfigType("yml")
	viper.SetConfigName(ConfigName)
	if err := viper.ReadInConfig(); err != nil {
		return nil, err
	}

	// Unmarshal config
	var config Configuration
	if err := viper.Unmarshal(&config); err != nil {
		return nil, err
	}

	return &config, nil
}

func WriteDefault() error {
	executable, err := os.Executable()
	if err != nil {
		return err
	}

	configFilePath := filepath.Join(filepath.Dir(executable), ConfigName+".yml")
	return os.WriteFile(configFilePath, defaultConfiguration, 0600)
}

// GetRefreshRate returns the refresh rate as duration
func (c *Configuration) GetRefreshRate() time.Duration {
	refreshRate, err := time.ParseDuration(c.RefreshRate)
	if err != nil {
		log.Panic().Msgf("unable to parse refresh rate: %s. Please check your configuration.", c.RefreshRate)
	}
	return refreshRate
}

func (c *Configuration) GetTranslator() (translate.Translator, error) {
	var translator translate.Translator
	var err error
	switch c.Translator.API {
	case "google":
		translator, err = translate.NewGoogle(c.Translator.To)
	case "deepl":
		translator, err = translate.NewDeepL(c.Translator.To, c.Translator.AuthenticationKey)
	default:
		log.Fatal().Msgf("unsupported translator api: %s", c.Translator.API)
	}
	if err != nil {
		return nil, err
	}
	return translator, nil
}

func parseColorString(s string) (color.RGBA, error) {
	var c color.RGBA
	if len(s) != 7 {
		return c, fmt.Errorf("color string length must be 7 but is %d", len(s))
	}
	if _, err := fmt.Sscanf(s, "#%02x%02x%02x", &c.R, &c.G, &c.B); err != nil {
		return c, fmt.Errorf("unable to parse color string %s", s)
	}
	return c, nil
}

func (f *Font) GetColor() (color.RGBA, error) {
	color, err := parseColorString(f.Color)
	if err != nil {
		return color, fmt.Errorf("invalid `subs.font.color` value: %w", err)
	}
	color.A = uint8(0xFF)
	return color, nil
}

func (b *Background) GetColor() (color.RGBA, error) {
	color, err := parseColorString(b.Color)
	if err != nil {
		return color, fmt.Errorf("invalid `subs.background.color` value: %w", err)
	}
	color.A = uint8(b.Opacity)
	return color, nil
}
