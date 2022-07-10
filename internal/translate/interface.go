package translate

type Translator interface {
	Translate(toTranslate string) (string, error)
	Close()
}
