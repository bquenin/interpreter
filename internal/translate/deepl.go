package translate

import (
	"encoding/json"
	"golang.org/x/text/language"
	"net/http"
	"net/url"
	"strings"
)

const (
	apiURL = "https://api-free.deepl.com/v2/translate"
)

type DeepL struct {
	target            language.Tag
	authenticationKey string
}

func NewDeepL(translateTo, authenticationKey string) (*DeepL, error) {
	language, err := language.Parse(translateTo)
	if err != nil {
		return nil, err
	}
	return &DeepL{language, authenticationKey}, nil
}

type DeepLResponse struct {
	Translations []Translations `json:"translations"`
}

type Translations struct {
	DetectedSourceLanguage string `json:"detected_source_language"`
	Text                   string `json:"text"`
}

func (d *DeepL) Translate(source string) (string, error) {
	u, _ := url.Parse(apiURL)

	urlData := url.Values{}
	urlData.Set("auth_key", d.authenticationKey)
	urlData.Set("target_lang", d.target.String())
	urlData.Set("text", source)

	client := &http.Client{}
	r, _ := http.NewRequest(http.MethodPost, u.String(), strings.NewReader(urlData.Encode())) // URL-encoded payload
	r.Header.Add("Content-Type", "application/x-www-form-urlencoded")

	resp, err := client.Do(r)
	defer resp.Body.Close()
	if err != nil {
		return "", err
	}

	var deepL DeepLResponse
	if err := json.NewDecoder(resp.Body).Decode(&deepL); err != nil {
		return "", err
	}

	if len(deepL.Translations) == 0 {
		return "", nil
	}

	return deepL.Translations[0].Text, nil
}

func (d *DeepL) Close() {}
