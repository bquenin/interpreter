package main

import (
	"bytes"
	"context"
	"errors"
	"flag"
	"fmt"
	"github.com/spf13/viper"
	"image"
	"image/color"
	"image/jpeg"
	"os"
	"time"

	"cloud.google.com/go/vision/apiv1"
	"github.com/bquenin/captured"
	"github.com/bquenin/interpreter/cmd/interpreter/configuration"
	"github.com/bquenin/interpreter/internal/translate"
	"github.com/hajimehoshi/ebiten/v2"
	"github.com/hajimehoshi/ebiten/v2/ebitenutil"
	"github.com/hajimehoshi/ebiten/v2/examples/resources/fonts"
	"github.com/hajimehoshi/ebiten/v2/text"
	"github.com/k0kubun/pp/v3"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	"golang.org/x/image/font"
	"golang.org/x/image/font/opentype"
	visionpb "google.golang.org/genproto/googleapis/cloud/vision/v1"
)

func init() {
	zerolog.SetGlobalLevel(zerolog.InfoLevel)
	log.Logger = log.Output(zerolog.ConsoleWriter{Out: os.Stdout, TimeFormat: time.RFC3339})
}

type App struct {
	visionClient        *vision.ImageAnnotatorClient
	windowTitle         string
	refreshRate         time.Duration
	lastUpdate          time.Time
	subsFont            font.Face
	lastText            string
	subs                string
	confidenceThreshold float32
	translator          translate.Translator
	debug               bool
}

func filterTextByConfidence(annotation *visionpb.TextAnnotation, threshold float32) string {
	var buffer bytes.Buffer
	for _, page := range annotation.Pages {
		for _, block := range page.Blocks {
			for _, paragraph := range block.Paragraphs {
				for _, word := range paragraph.Words {
					if word.Confidence < threshold {
						continue
					}
					for _, s := range word.Symbols {
						buffer.WriteString(s.Text)
					}
				}
			}
		}
	}
	return buffer.String()
}

func (a *App) screenshot(windowTitle string) (image.Image, error) {
	return captured.Captured.CaptureWindowByTitle(windowTitle, captured.CropTitle)
}

func (a *App) annotate(image image.Image) (string, error) {
	// Encode to JPEG
	var buffer bytes.Buffer
	if err := jpeg.Encode(&buffer, image, &jpeg.Options{Quality: 85}); err != nil {
		return "", err
	}

	// Create image
	img, err := vision.NewImageFromReader(&buffer)
	if err != nil {
		return "", err
	}

	// Extract text from image
	annotation, err := a.visionClient.DetectDocumentText(context.Background(), img, nil)
	if err != nil {
		return "", err
	}
	if annotation == nil {
		log.Warn().Msg("no text found")
		return "", nil
	}

	// Filter out gibberish
	extractedText := filterTextByConfidence(annotation, a.confidenceThreshold)
	if extractedText == "" {
		log.Warn().Msgf("no text found with confidence threshold %f", a.confidenceThreshold)
		return "", nil
	}

	log.Info().Msgf("extracted text: %s", extractedText)
	return extractedText, nil
}

func (a *App) Update() error {
	// Move window handler
	if ebiten.IsMouseButtonPressed(ebiten.MouseButtonLeft) {
		x, y := ebiten.CursorPosition()
		cx, cy := ebiten.WindowPosition()
		ebiten.SetWindowPosition(x+cx, y+cy)
	}

	// Check if it's time to refresh
	if !time.Now().After(a.lastUpdate.Add(a.refreshRate)) {
		return nil
	}
	a.lastUpdate = time.Now()

	go func() {
		screenshot, err := a.screenshot(a.windowTitle)
		if err != nil {
			log.Fatal().Err(err).Send()
		}

		if a.debug { // Save screenshot to disk
			f, err := os.Create(fmt.Sprintf("screenshot-%d.jpg", a.lastUpdate.UnixNano()))
			if err != nil {
				log.Fatal().Err(err).Send()
			}
			defer f.Close()
			if err = jpeg.Encode(f, screenshot, &jpeg.Options{Quality: 85}); err != nil {
				log.Fatal().Err(err).Send()
			}
		}

		text, err := a.annotate(screenshot)
		if err != nil {
			log.Fatal().Err(err).Send()
		}
		if text == a.lastText {
			return
		}
		if text == "" {
			a.subs = ""
			return
		}

		translation, err := a.translator.Translate(text)
		if err != nil {
			log.Fatal().Err(err).Send()
		}
		log.Info().Msgf("translated text: %s", translation)

		a.lastText = text
		a.subs = translation
	}()

	return nil
}

func (a *App) Draw(screen *ebiten.Image) {
	const x, y = 20, 96
	bound := text.BoundString(a.subsFont, a.subs)
	ebitenutil.DrawRect(screen, float64(bound.Min.X+x), float64(bound.Min.Y+y), float64(bound.Dx()), float64(bound.Dy()), color.RGBA{R: 0x40, G: 0x40, B: 0x40, A: 0xFF})
	text.Draw(screen, a.subs, a.subsFont, x, y, color.White)
}

func (a *App) Layout(outsideWidth, outsideHeight int) (int, int) {
	return outsideWidth, outsideHeight
}

func NewTranslator(config *configuration.Configuration) (translate.Translator, error) {
	var translator translate.Translator
	var err error
	switch config.Translator.API {
	case "google":
		translator, err = translate.NewGoogle(config.Translator.To)
	case "deepl":
		translator, err = translate.NewDeepL(config.Translator.To, config.Translator.AuthenticationKey)
	default:
		log.Fatal().Msgf("unsupported translator api: %s", config.Translator.API)
	}
	if err != nil {
		return nil, err
	}
	return translator, nil
}

func main() {
	width, height := ebiten.ScreenSizeInFullscreen()
	ebiten.SetWindowSize(width, height*20/100)
	ebiten.SetWindowTitle("Interpreter")
	ebiten.SetWindowDecorated(false)
	ebiten.SetWindowFloating(true)
	ebiten.SetScreenTransparent(true)

	// Read configuration
	config, err := configuration.Read()
	if err != nil {
		var configNotFound viper.ConfigFileNotFoundError
		switch {
		case errors.As(err, &configNotFound):
			log.Info().Msg("Configuration file not found: Creating default configuration file")
			if err = configuration.WriteDefault(); err != nil {
				log.Fatal().Err(err).Send()
			}
			log.Info().Msg("Default configuration file successfully created.")
			return
		default:
			log.Fatal().Err(err).Send()
		}
	}
	debug := flag.Bool("d", false, "enable debug mode")
	flag.Parse()
	if *debug {
		config.Debug = true
	}
	log.Info().Msg(pp.Sprint(config))

	// Vision
	visionClient, err := vision.NewImageAnnotatorClient(context.Background())
	if err != nil {
		log.Fatal().Err(err).Send()
	}
	defer visionClient.Close()

	// Translator
	translator, err := NewTranslator(config)
	if err != nil {
		log.Fatal().Err(err).Send()
	}
	defer translator.Close()

	// Font
	ttf, err := opentype.Parse(fonts.MPlus1pRegular_ttf)
	if err != nil {
		log.Fatal().Err(err).Send()
	}
	fontFace, err := opentype.NewFace(ttf, &opentype.FaceOptions{
		Size:    48,
		DPI:     72,
		Hinting: font.HintingFull,
	})
	if err != nil {
		log.Fatal().Err(err).Send()
	}

	app := &App{
		visionClient:        visionClient,
		translator:          translator,
		subsFont:            fontFace,
		windowTitle:         config.WindowTitle,
		refreshRate:         config.GetRefreshRate(),
		confidenceThreshold: config.ConfidenceThreshold,
		debug:               config.Debug,
	}
	if err := ebiten.RunGame(app); err != nil {
		log.Fatal().Err(err).Send()
	}
}
