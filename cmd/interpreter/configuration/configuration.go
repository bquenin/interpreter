package configuration

import (
	"strings"
	"time"

	"github.com/rs/zerolog/log"
	"github.com/spf13/viper"
)

const (
	ConfigName = "interpreter"
)

type Translator struct {
	To                string `mapstructure:"to"`
	API               string `mapstructure:"api"`
	AuthenticationKey string `mapstructure:"authentication-key"`
}

type Configuration struct {
	WindowTitle         string     `mapstructure:"window-title"`
	RefreshRate         string     `mapstructure:"refresh-rate"`
	ConfidenceThreshold float32    `mapstructure:"confidence-threshold"`
	Translator          Translator `mapstructure:"translator"`
	Debug               bool
}

func Read() (*Configuration, error) {
	// Add matching environment variables - will take precedence over config files.
	viper.AutomaticEnv()
	viper.SetEnvKeyReplacer(strings.NewReplacer(".", "_", "-", "_"))
	viper.SetEnvPrefix("INTERPRETER")

	// Add default config file search paths in order of decreasing precedence.
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

// GetRefreshRate returns the refresh rate as duration
func (c *Configuration) GetRefreshRate() time.Duration {
	refreshRate, err := time.ParseDuration(c.RefreshRate)
	if err != nil {
		log.Panic().Msgf("unable to parse refresh rate: %s. Please check your configuration.", c.RefreshRate)
	}
	return refreshRate
}
