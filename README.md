# Dowpedia News Bot
This repository automates the process of fetching financial news and generating structured articles for Dowpedia using Finnhub and Gemini AI.

## Workflow
- Runs periodically via GitHub Actions.
- Fetches the latest general financial news.
- Evaluates, scores and categorizes the news.
- Generates high-quality articles in English and Chinese using Gemini AI.
- Saves the output to `public/haberler.json` for consumption by the main Dowpedia app.
