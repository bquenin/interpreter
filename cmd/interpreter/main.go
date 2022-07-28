package main

import (
	"bytes"
	"context"
	"errors"
	"flag"
	"fmt"
	"github.com/hajimehoshi/ebiten/v2/inpututil"
	"image"
	"image/color"
	"image/jpeg"
	"os"
	"strings"
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
	"github.com/spf13/viper"
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
	subsFontColor       color.RGBA
	subsBackgroundColor color.RGBA
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
	if inpututil.IsKeyJustPressed(ebiten.KeyT) {
		ebiten.SetWindowDecorated(!ebiten.IsWindowDecorated())
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
	width, height := ebiten.WindowSize()
	if ebiten.IsWindowDecorated() {
		ebitenutil.DrawRect(screen, 0, 0, float64(width), float64(height), color.Black)
		message := "Press T to toggle window"
		if a.subs == "" {
			message += "\n[no text detected]"
		}
		ebitenutil.DebugPrint(screen, message)
	}

	if a.subs == "" {
		return
	}

	var line, subtitles bytes.Buffer
	for _, word := range strings.Fields(a.subs) {
		bound := text.BoundString(a.subsFont, line.String()+word)
		if bound.Dx() > width {
			subtitles.WriteString(line.String())
			subtitles.WriteString("\n")
			line = bytes.Buffer{}
		}
		line.WriteString(word)
		line.WriteString(" ")
	}
	subtitles.WriteString(line.String())

	bound := text.BoundString(a.subsFont, subtitles.String())
	boxSize := image.Point{X: bound.Max.X, Y: bound.Dy() + a.subsFont.Metrics().Height.Round()}

	x := 0
	if boxSize.X < width {
		x = (width - boxSize.X) / 2
	}
	ebitenutil.DrawRect(screen, float64(x), float64(0), float64(boxSize.X), float64(boxSize.Y), a.subsBackgroundColor)
	text.Draw(screen, subtitles.String(), a.subsFont, x, a.subsFont.Metrics().Height.Round(), a.subsFontColor)
}

func (a *App) Layout(outsideWidth, outsideHeight int) (int, int) {
	return outsideWidth, outsideHeight
}

func main() {
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
	translator, err := config.GetTranslator()
	if err != nil {
		log.Fatal().Err(err).Send()
	}
	defer translator.Close()

	// Font
	fontColor, err := config.Subs.Font.GetColor()
	if err != nil {
		log.Fatal().Err(err).Send()
	}

	backgroundColor, err := config.Subs.Background.GetColor()
	if err != nil {
		log.Fatal().Err(err).Send()
	}

	ttf, err := opentype.Parse(fonts.MPlus1pRegular_ttf)
	if err != nil {
		log.Fatal().Err(err).Send()
	}
	fontFace, err := opentype.NewFace(ttf, &opentype.FaceOptions{
		Size:    float64(config.Subs.Font.Size),
		DPI:     72,
		Hinting: font.HintingFull,
	})
	if err != nil {
		log.Fatal().Err(err).Send()
	}

	ebiten.SetWindowTitle("Interpreter")
	ebiten.SetScreenTransparent(true)
	ebiten.SetWindowFloating(true)
	ebiten.SetWindowResizingMode(ebiten.WindowResizingModeEnabled)

	app := &App{
		visionClient:        visionClient,
		translator:          translator,
		subsFont:            fontFace,
		subsFontColor:       fontColor,
		subsBackgroundColor: backgroundColor,
		windowTitle:         config.WindowTitle,
		refreshRate:         config.GetRefreshRate(),
		confidenceThreshold: config.ConfidenceThreshold,
		debug:               config.Debug,
	}
	if err := ebiten.RunGame(app); err != nil {
		log.Fatal().Err(err).Send()
	}
}
