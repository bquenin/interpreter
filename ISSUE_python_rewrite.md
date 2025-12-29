# Feature: Rewrite in Python with offline OCR and translation

## Summary

Explore rewriting the application in Python with **fully offline** OCR and translation capabilities, eliminating the need for Google Cloud Vision and Google Translate/DeepL API accounts.

## Motivation

- **No API costs** - Free after initial setup
- **Privacy** - Text never leaves the user's machine
- **Simpler setup** - No cloud account/API key configuration required
- **Offline usage** - Works without internet connection

## Offline OCR Options

| Library | Pros | Cons |
|---------|------|------|
| **Tesseract** (pytesseract) | Mature, lightweight, good Japanese support | Accuracy varies on stylized text |
| **EasyOCR** | Deep learning, excellent CJK support | ~100MB+ models, slower |
| **PaddleOCR** | Very accurate for Asian languages | Larger footprint |
| **manga-ocr** | Specifically trained for Japanese game/manga text | Narrow use case |

**Recommendation:** `EasyOCR` or `manga-ocr` for Japanese game text

## Offline Translation Options

| Library | Pros | Cons |
|---------|------|------|
| **Argos Translate** | Simple API, offline, ~100MB per language pair | Quality not as good as Google/DeepL |
| **Helsinki-NLP Opus-MT** (via transformers) | Good quality, many language pairs | Large models (~300MB+), needs GPU for speed |
| **CTranslate2** | Optimized inference, faster on CPU | More setup required |

**Recommendation:** `Argos Translate` for simplicity, or `Opus-MT` for better quality

## Screen Capture & UI

- **mss** or **pyautogui** for cross-platform screenshots
- **tkinter** for transparent floating overlay (built-in, minimal dependencies)
- **PyQt6** as alternative for more advanced UI

## Trade-offs vs Current Implementation

| Aspect | Go + Cloud APIs | Python + Offline |
|--------|-----------------|------------------|
| **Accuracy** | Excellent (Google Vision) | Good (varies by model) |
| **Speed** | Network latency | Local inference (GPU helps) |
| **Cost** | API fees | Free after setup |
| **Privacy** | Text sent to cloud | Fully local |
| **Setup** | API keys required | Download models (~1-2GB) |
| **Dependencies** | Minimal | Heavier (PyTorch/ONNX) |

## Implementation Considerations

1. **Model size** - Users will need to download OCR + translation models (~1-2GB total)
2. **Performance** - Without GPU, inference may be slower but still usable at 5s+ refresh intervals
3. **Japanese font handling** - Game fonts can be stylized; manga-ocr specifically handles this
4. **Cross-platform** - All suggested libraries support Windows and macOS

## Proposed Tech Stack

```
Python 3.10+
├── OCR: EasyOCR or manga-ocr
├── Translation: Argos Translate
├── Screen capture: mss
├── UI: tkinter (transparent overlay)
└── Config: PyYAML
```

## Tasks

- [ ] Set up Python project structure
- [ ] Implement screen capture by window title
- [ ] Integrate offline OCR (EasyOCR/manga-ocr)
- [ ] Integrate offline translation (Argos Translate)
- [ ] Create transparent floating subtitle overlay
- [ ] Add configuration file support (mirror current config.yml format)
- [ ] Test with Japanese games
- [ ] Document model download/setup process
