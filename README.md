# Interpreter

This app can translate text captured from any application running on your computer. You just need to 
specify which window you want to sample and that's it.

The app uses Google Cloud Vision and Cloud Translate APIs to:
* Extract the text on-screen
* Translate it to a given language

The translated text is then displayed as subtitles on a floating window that you can move anywhere.

It's typically used to translate Japanese retro games unreleased in the US but you can use for anything you wish to translate!

![sample](sample.jpg)

# How to use

Before you can use this app, you need some prerequisites:

* A Google Cloud account
* Go installed on your computer  

## Getting a Google Cloud account 

In order to use this application, you need to have a Google Cloud account:

* Sign up to Google Cloud here for free: https://cloud.google.com/free or use your existing account.

### Create or Select a Project

* https://cloud.google.com/translate/docs/setup#project

### Enable billing

* https://cloud.google.com/translate/docs/setup#billing

### Enable Cloud Vision API

* https://cloud.google.com/vision/docs/setup#api

### Enable Cloud Translation

* https://cloud.google.com/translate/docs/setup#api

### Create Service Accounts and Keys

* https://cloud.google.com/translate/docs/setup#creating_service_accounts_and_keys

### Use the Service Account Key File in Your Environment

* https://cloud.google.com/translate/docs/setup#using_the_service_account_key_file_in_your_environment

## Installing Go

In order to install go on your machine, follow the instructions here: https://go.dev/doc/install

## Cloning the repository

```
git clone https://github.com/bquenin/interpreter.git
cd interpreter
```

## Configure Interpreter

Update the `interpreter.yml` configuration file:

```yml
window-title: "" # specify the name of the window you want to capture
translate-to: "en"
refresh-rate: "5s"
confidence-threshold: 0.9
```

## Run Interpreter

```
go run ./cmd/interpreter/main.go
```
