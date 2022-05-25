package main

import (
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
	"github.com/hajimehoshi/ebiten/v2"
	"github.com/hajimehoshi/ebiten/v2/ebitenutil"
	"github.com/hajimehoshi/ebiten/v2/examples/resources/fonts"
	"github.com/hajimehoshi/ebiten/v2/text"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	"golang.org/x/image/font"
	"golang.org/x/image/font/opentype"
	"golang.org/x/text/language"
)

func init() {
	zerolog.SetGlobalLevel(zerolog.InfoLevel)
	log.Logger = log.Output(zerolog.ConsoleWriter{Out: os.Stdout, TimeFormat: time.RFC3339})

}

type App struct {
	visionClient      *vision.ImageAnnotatorClient
	translationClient *translate.Client
	windowTitle       string
	translateTo       language.Tag
	refreshRate       time.Duration
	lastUpdate        time.Time
	subsFont          font.Face
	subs              string
}

func (a *App) annotateAndTranslate() (string, error) {
	// Capture window
	img, err := captured.Captured.CaptureWindowByTitle(a.windowTitle, captured.CropTitle)
	if err != nil {
		return "", err
	}

	// Encode to JPEG
	pr, pw := io.Pipe()
	go func() {
		defer pw.Close()
		if err = jpeg.Encode(pw, img, &jpeg.Options{Quality: 85}); err != nil {
			log.Fatal().Err(err).Send()
		}
	}()

	// Create image from pipe output
	image, err := vision.NewImageFromReader(pr)
	if err != nil {
		return "", err
	}

	// Extract text from image
	annotations, err := a.visionClient.DetectTexts(context.Background(), image, nil, 1)
	if err != nil {
		return "", err
	}
	if len(annotations) == 0 {
		log.Warn().Msg("no text found")
		return "", nil
	}
	extractedText := annotations[0].Description
	log.Debug().Msgf("extracted text: %s", extractedText)

	// Translate text
	resp, err := a.translationClient.Translate(context.Background(), []string{extractedText}, a.translateTo, nil)
	if err != nil {
		return "", err
	}
	if len(resp) == 0 {
		log.Warn().Msgf("translate returned empty response to text: %s", extractedText)
		return "", nil
	}
	translatedText := html.UnescapeString(resp[0].Text)
	log.Debug().Msgf("translated text: %s", translatedText)

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
		translation, err := a.annotateAndTranslate()
		if err != nil {
			log.Fatal().Err(err).Send()
		}
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

	// Get configuration
	config := NewConfiguration()
	if err := config.ReadConfiguration(); err != nil {
		log.Fatal().Err(err).Send()
	}

	// Vision Client
	visionClient, err := vision.NewImageAnnotatorClient(context.Background())
	if err != nil {
		log.Fatal().Err(err).Send()
	}
	defer visionClient.Close()

	// Translate Client
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
		visionClient:      visionClient,
		translationClient: translateClient,
		subsFont:          fontFace,
		windowTitle:       config.WindowTitle,
		translateTo:       target,
		refreshRate:       config.GetRefreshRate(),
	}
	if err := ebiten.RunGame(app); err != nil {
		log.Fatal().Err(err).Send()
	}
}
