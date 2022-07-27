# Interpreter

This app can translate text captured from any application running on your computer. You just need to 
specify which window you want to sample and that's it.

The app uses:
* Google Cloud Vision to Extract the text on-screen
* Google Translate or DeepL to translate it

The translated text is then displayed as subtitles on a floating window that you can move anywhere.

It's typically used to translate Japanese retro games unreleased in the US but you can use for anything you wish to translate!

![sample](sample.jpg)

# How to use

Before you can use this app, you need some prerequisites:

* A Google Cloud account.
* Alternatively, you can use DeepL instead of Google Translate for translation.

## Setting up your Google Cloud account

### [Check the video tutorial](https://www.youtube.com/watch?v=FLt-UyoNW9w)

* [Get a free Google Cloud account here](https://cloud.google.com/free) or use your existing account.
* [Create or Select a project](https://cloud.google.com/translate/docs/setup#project)
* [Enable billing](https://cloud.google.com/translate/docs/setup#billing)
* [Enable Cloud Vision API](https://cloud.google.com/vision/docs/setup#api) 
* [Enable Cloud Translation](https://cloud.google.com/translate/docs/setup#api) (You can skip this step if you're using the DeepL API)
* [Create Service Accounts and Keys](https://cloud.google.com/translate/docs/setup#creating_service_accounts_and_keys)
* [Use the Service Account Key File in Your Environment](https://cloud.google.com/translate/docs/setup#using_the_service_account_key_file_in_your_environment)
* Update the configuration file accordingly:
```yml
translator:
  api: "google"
  to: "en" # Target language
```

> Note: The list of Google Translate supported language is available [here](https://cloud.google.com/translate/docs/languages).

## (Optional) Setting up your DeepL account

As an alternative to Google Translate, you can use DeepL translate:

* [Get a free DeepL account here](https://www.deepl.com/pro-checkout/account?productId=1200&yearly=false&trial=false) or use your existing account.
* Update the configuration file accordingly:
```yml
translator:
  api: "deepl"
  to: "en" # Target language
  authentication-key: "your-deepl-authentication-key"
```

> Note: The list of DeepL supported language is available [here](https://www.deepl.com/en/docs-api/translating-text).
 
## Creating the default configuration file

If you run `interpreter` and no configuration file is found, `interpreter` will create the default
configuration file in the current folder and then exit.

You can now make the required change to the configuration file.

Once you are done, you can run `interpreter` again to start translating an application.

## Configure Interpreter

Update the `config.yml` configuration file:

```yml
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
