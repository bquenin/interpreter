package translate

import (
	"context"
	"html"

	"cloud.google.com/go/translate"
	"golang.org/x/text/language"
)

type Google struct {
	client *translate.Client
	target language.Tag
}

func NewGoogle(translateTo string) (*Google, error) {
	client, err := translate.NewClient(context.Background())
	if err != nil {
		return nil, err
	}

	language, err := language.Parse(translateTo)
	if err != nil {
		return nil, err
	}
	return &Google{client, language}, nil
}

func (g *Google) Translate(source string) (string, error) {
	translation, err := g.client.Translate(context.Background(), []string{source}, g.target, nil)
	if err != nil {
		return "", err
	}
	if len(translation) == 0 {
		return "", nil
	}

	translatedText := html.UnescapeString(translation[0].Text)
	return translatedText, nil
}

func (g *Google) Close() {
	_ = g.client.Close()
}
