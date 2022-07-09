package main

import (
	"bytes"
	"context"
	"html"
	"image/color"
	"image/jpeg"
	"io"
	"os"
	"time"

	"cloud.google.com/go/translate"
	"cloud.google.com/go/vision/apiv1"
	"github.com/bquenin/captured"
	"github.com/bquenin/interpreter/cmd/interpreter/configuration"
	"github.com/hajimehoshi/ebiten/v2"
	"github.com/hajimehoshi/ebiten/v2/ebitenutil"
	"github.com/hajimehoshi/ebiten/v2/examples/resources/fonts"
	"github.com/hajimehoshi/ebiten/v2/text"
	"github.com/k0kubun/pp/v3"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	"golang.org/x/image/font"
	"golang.org/x/image/font/opentype"
	"golang.org/x/text/language"
	visionpb "google.golang.org/genproto/googleapis/cloud/vision/v1"
)

func init() {
	zerolog.SetGlobalLevel(zerolog.InfoLevel)
	log.Logger = log.Output(zerolog.ConsoleWriter{Out: os.Stdout, TimeFormat: time.RFC3339})

}

type App struct {
	visionClient        *vision.ImageAnnotatorClient
	translationClient   *translate.Client
	windowTitle         string
	translateTo         language.Tag
	refreshRate         time.Duration
	lastUpdate          time.Time
	subsFont            font.Face
	lastText            string
	subs                string
	confidenceThreshold float32
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

func (a *App) screenshot(windowTitle string) (*bytes.Buffer, error) {
	// Capture window
	img, err := captured.Captured.CaptureWindowByTitle(windowTitle, captured.CropTitle)
	if err != nil {
		return nil, err
	}

	// Encode to JPEG
	var buffer bytes.Buffer
	if err = jpeg.Encode(&buffer, img, &jpeg.Options{Quality: 85}); err != nil {
		return nil, err
	}
	return &buffer, nil
}

func (a *App) annotate(image io.Reader) (string, error) {
	// Create img
	img, err := vision.NewImageFromReader(image)
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

func (a *App) translate(toTranslate string) (string, error) {
	// translate text
	translation, err := a.translationClient.Translate(context.Background(), []string{toTranslate}, a.translateTo, nil)
	if err != nil {
		return "", err
	}
	if len(translation) == 0 {
		log.Warn().Msgf("translate returned empty response to text: %s", toTranslate)
		return "", nil
	}

	translatedText := html.UnescapeString(translation[0].Text)
	log.Info().Msgf("translated text: %s", translatedText)
	return translatedText, nil
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
		ss, err := a.screenshot(a.windowTitle)
		if err != nil {
			log.Fatal().Err(err).Send()
		}

		text, err := a.annotate(ss)
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

		translation, err := a.translate(text)
		if err != nil {
			log.Fatal().Err(err).Send()
		}

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
		log.Fatal().Err(err).Send()
	}
	log.Info().Msg(pp.Sprint(config))

	// Vision Client
	visionClient, err := vision.NewImageAnnotatorClient(context.Background())
	if err != nil {
		log.Fatal().Err(err).Send()
	}
	defer visionClient.Close()

	// translate Client
	translateClient, err := translate.NewClient(context.Background())
	if err != nil {
		log.Fatal().Err(err).Send()
	}
	defer translateClient.Close()

	// Target language
	target, err := language.Parse(config.TranslateTo)
	if err != nil {
		log.Fatal().Err(err).Send()
	}

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
		translationClient:   translateClient,
		subsFont:            fontFace,
		windowTitle:         config.WindowTitle,
		translateTo:         target,
		refreshRate:         config.GetRefreshRate(),
		confidenceThreshold: config.ConfidenceThreshold,
	}
	if err := ebiten.RunGame(app); err != nil {
		log.Fatal().Err(err).Send()
	}
}
