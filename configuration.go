package main

import (
	"strings"
	"time"

	"github.com/rs/zerolog/log"
	"github.com/spf13/viper"
)

const (
	ConfigName = "interpreter"
)

type Configuration struct {
	WindowTitle string `mapstructure:"window-title"`
	RefreshRate string `mapstructure:"refresh-rate"`
	TranslateTo string `mapstructure:"translate-to"`
}

func NewConfiguration() *Configuration {
	return &Configuration{} // Default Configuration
}

// ReadConfiguration reads the configuration
func (c *Configuration) ReadConfiguration() error {
	// Add matching environment variables - will take precedence over config files.
	viper.AutomaticEnv()

	// Sets the String replacer for environment variables to have names with underscores only
	viper.SetEnvKeyReplacer(strings.NewReplacer(".", "_", "-", "_"))

	// Sets the prefix for environment variables, e.g. INTERPRETER_TITLE
	viper.SetEnvPrefix("INTERPRETER")

	// Add default config file search paths in order of decreasing precedence.
	viper.AddConfigPath(".")
	viper.AddConfigPath("$HOME")
	viper.SetConfigType("yml")
	viper.SetConfigName(ConfigName)
	if err := viper.ReadInConfig(); err != nil {
		return err
	}

	// Unmarshal config into Configuration object
	if err := viper.Unmarshal(c); err != nil {
		return err
	}

	return nil
}

// GetRefreshRate returns the refresh rate as duration
func (c *Configuration) GetRefreshRate() time.Duration {
	refreshRate, err := time.ParseDuration(c.RefreshRate)
	if err != nil {
		log.Panic().Msgf("unable to parse refresh rate: %s. Please check your configuration.", c.RefreshRate)
	}
	return refreshRate
}
