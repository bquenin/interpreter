# Interpreter

This app can translate text captured from any application running on your computer. You just need to 
specify which window you want to sample and that's it!

The app uses:
* Google Cloud Vision to extract the text on-screen
* Google Translate or DeepL to translate it

The translated text is then displayed as subtitles on a floating window that you can move anywhere.

It's typically used to translate Japanese retro games unreleased in the US, but you can use it for anything you wish to translate!

![sample](sample.jpg)

# How to Use

## Video Tutorial

[Check out the video tutorial](https://www.youtube.com/watch?v=FLt-UyoNW9w) for a visual walkthrough of the setup process.

## Prerequisites

Before you can use this app, you need the following:

* A Google Cloud account
* Alternatively, you can use DeepL instead of Google Translate for translation

## Setting Up Your Google Cloud Account

* [Get a free Google Cloud account here](https://cloud.google.com/free) or use your existing account
* [Create or select a project](https://cloud.google.com/translate/docs/setup#project)
* [Enable billing](https://cloud.google.com/translate/docs/setup#billing)
* [Enable Cloud Vision API](https://cloud.google.com/vision/docs/setup#api) 
* [Enable Cloud Translation](https://cloud.google.com/translate/docs/setup#api) (You can skip this step if you're using the DeepL API)
* [Create service accounts and keys](https://cloud.google.com/translate/docs/setup#creating_service_accounts_and_keys)
* [Use the service account key file in your environment](https://cloud.google.com/translate/docs/setup#using_the_service_account_key_file_in_your_environment)
* Update the [configuration file](config.yml) accordingly:

```yaml
translator:
  api: "google"
  to: "en" # Target language
```

> **Note:** The list of Google Translate supported languages is available [here](https://cloud.google.com/translate/docs/languages).

## (Optional) Setting Up Your DeepL Account

As an alternative to Google Translate, you can use DeepL for translation:

* [Get a free DeepL account here](https://www.deepl.com/pro-checkout/account?productId=1200&yearly=false&trial=false) or use your existing account
* Update the [configuration file](config.yml) accordingly:

```yaml
translator:
  api: "deepl"
  to: "en" # Target language
  authentication-key: "your-deepl-authentication-key"
```

> **Note:** The list of DeepL supported languages is available [here](https://www.deepl.com/en/docs-api/translating-text).
 
## Creating the Default Configuration File

If you run `interpreter` and no configuration file is found, `interpreter` will create the default
configuration file in the current folder and then exit.

You can make the required changes to the configuration file after that.

Once you are done, you can run `interpreter` again to start translating an application.

## Configure Interpreter

Update the [`config.yml`](config.yml) configuration file:

```yaml
window-title: "change me"               # Title of the window you want to capture. It can be any part of the window title, for instance "Tales" for "Tales of Phantasia".
refresh-rate: "5s"                      # How often a screenshot is taken
confidence-threshold: 0.9               # Between 0 and 1. Filters out any OCR character with a confidence score below the threshold.
translator:
  api: "google"                         # "google" or "deepl"
  to: "en"                              # Target language. For Google translate, please check here: https://cloud.google.com/translate/docs/languages. For deepL, please check here: https://www.deepl.com/en/docs-api/translating-text
  authentication-key: "deepl-auth-key"  # required only for deepL
subs:
  font:
    color: "#FFFFFF"                      # RGB color code
    size: 48                              # Font size
  background:
    color: "#404040"                      # RGB color code
    opacity: 0xD0                         # Between 0x00 (transparent) and 0xFF (opaque)
```

## Troubleshooting

### Why does my virus-scanning software think `interpreter` is infected?

This is a common occurrence, especially on Windows machines, and is always a false positive. Commercial virus
scanning programs are often confused by the structure of Go binaries, which they don't see as often as those compiled
from other languages.

Read more about it [here](https://go.dev/doc/faq#virus).
