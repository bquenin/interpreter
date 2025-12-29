# Feature: Add offline OCR and translation support

## Summary

Add **fully offline** OCR and translation capabilities, eliminating the need for Google Cloud Vision and Google Translate/DeepL API accounts.

## Motivation

- **No API costs** - Free after initial setup
- **Privacy** - Text never leaves the user's machine
- **Simpler setup** - No cloud account/API key configuration required
- **Offline usage** - Works without internet connection

---

## Option 1: Go + Ollama (Recommended)

### Why This Approach?

Instead of rewriting the entire application, keep the existing Go codebase and swap cloud APIs for a local LLM via Ollama. A vision-capable model can handle both OCR and translation in a single call.

| Factor | Go + Ollama | Python Rewrite |
|--------|-------------|----------------|
| Rewrite effort | Minimal (~50 lines) | Full rewrite |
| Dependencies | Just Ollama | Python + PyTorch + models |
| User setup | `ollama pull llava` | pip install + model downloads |
| Maintenance | Keep existing codebase | New codebase to maintain |

### How It Works

```
Screenshot → Vision LLM (LLaVA, Qwen2-VL) → "Extract Japanese text and translate to English"
```

A single model handles both OCR and translation, simplifying the pipeline significantly.

### Implementation Sketch

```go
import "github.com/ollama/ollama/api"

func (a *App) processImage(img image.Image) (string, error) {
    // Encode image to base64
    var buf bytes.Buffer
    jpeg.Encode(&buf, img, nil)
    imgBase64 := base64.StdEncoding.EncodeToString(buf.Bytes())

    // Call Ollama with vision model
    resp, err := client.Generate(ctx, &api.GenerateRequest{
        Model:  "llava",  // or qwen2-vl, minicpm-v, etc.
        Prompt: "Extract all Japanese text from this image and translate it to English. Only output the translation.",
        Images: []api.ImageData{imgBase64},
    })
    return resp.Response, nil
}
```

### Recommended Vision Models

| Model | Size | Notes |
|-------|------|-------|
| **llava** | ~4GB | Good general purpose |
| **qwen2-vl** | ~4-8GB | Excellent for Asian languages |
| **minicpm-v** | ~3GB | Lightweight, fast |

### Tasks (Option 1)

- [ ] Add Ollama Go SDK dependency
- [ ] Create Ollama-based translator/OCR implementation
- [ ] Add configuration option to choose between cloud APIs and Ollama
- [ ] Update README with Ollama setup instructions
- [ ] Test with various vision models
- [ ] Benchmark latency vs cloud APIs

---

## Option 2: Python Rewrite

A full rewrite in Python gives access to the best ML/AI ecosystem but requires more effort.

### Offline OCR Options

| Library | Pros | Cons |
|---------|------|------|
| **Tesseract** (pytesseract) | Mature, lightweight, good Japanese support | Accuracy varies on stylized text |
| **EasyOCR** | Deep learning, excellent CJK support | ~100MB+ models, slower |
| **PaddleOCR** | Very accurate for Asian languages | Larger footprint |
| **manga-ocr** | Specifically trained for Japanese game/manga text | Narrow use case |

**Recommendation:** `EasyOCR` or `manga-ocr` for Japanese game text

### Offline Translation Options

| Library | Pros | Cons |
|---------|------|------|
| **Argos Translate** | Simple API, offline, ~100MB per language pair | Quality not as good as Google/DeepL |
| **Helsinki-NLP Opus-MT** (via transformers) | Good quality, many language pairs | Large models (~300MB+), needs GPU for speed |
| **CTranslate2** | Optimized inference, faster on CPU | More setup required |

**Recommendation:** `Argos Translate` for simplicity, or `Opus-MT` for better quality

### Screen Capture & UI

- **mss** or **pyautogui** for cross-platform screenshots
- **tkinter** for transparent floating overlay (built-in, minimal dependencies)
- **PyQt6** as alternative for more advanced UI

### Proposed Tech Stack

```
Python 3.10+
├── OCR: EasyOCR or manga-ocr
├── Translation: Argos Translate
├── Screen capture: mss
├── UI: tkinter (transparent overlay)
└── Config: PyYAML
```

### Tasks (Option 2)

- [ ] Set up Python project structure
- [ ] Implement screen capture by window title
- [ ] Integrate offline OCR (EasyOCR/manga-ocr)
- [ ] Integrate offline translation (Argos Translate)
- [ ] Create transparent floating subtitle overlay
- [ ] Add configuration file support (mirror current config.yml format)
- [ ] Test with Japanese games
- [ ] Document model download/setup process

---

## Trade-offs Comparison

| Aspect | Go + Cloud APIs | Go + Ollama | Python + Offline |
|--------|-----------------|-------------|------------------|
| **Accuracy** | Excellent | Good-Excellent | Good |
| **Speed** | Network latency | Local (GPU helps) | Local (GPU helps) |
| **Cost** | API fees | Free | Free |
| **Privacy** | Text sent to cloud | Fully local | Fully local |
| **Setup complexity** | API keys | Install Ollama + pull model | Python + pip + models |
| **Rewrite effort** | N/A | Minimal | Full rewrite |
| **Model size** | N/A | 3-8GB | 1-2GB |

## Recommendation

**Start with Option 1 (Go + Ollama)** - it provides the best ROI:
- Minimal code changes to existing codebase
- Single dependency (Ollama) handles everything
- Modern LLMs are excellent at both OCR and translation
- Can always fall back to Option 2 if quality isn't sufficient
