<img src="docs/app-icon.png" alt="CFB Sagarin app icon" width="96" align="right" />

# Sagarin College Football Ratings

A phone-friendly board for Jeff Sagarin's weekly college football ratings, published as a website and as an Android app.

Sagarin posts his ratings as one long plain-text file ([sagarin.com/sports/cfsend.htm](http://sagarin.com/sports/cfsend.htm)). This repo turns each weekly edition into a searchable, sortable page that works on a phone.

## What the board shows

| Tab | Contents |
| --- | --- |
| **Ratings** | All 266 rated FBS and FCS teams across his five systems (Rating, Predictor, Golden Mean, Recent, Strong Recent), plus record, schedule strength, and record vs. top 10 / top 30. Search, filter by division or conference, Top 25 toggle, and sort by any column. Tap a team for a "Why this rating" sheet built from the published numbers. |
| **Matchup Predictor** | Pick any two teams and where they play (either team's home field or a neutral site). The projected margin uses his method: rating difference plus the home advantage, for each of the five systems. |
| **Conferences** | Conference rankings by central mean, simple average, and the 50% win rating. |
| **Sagarin Predictions** | His published game predictions with each system's margin, win probability, and projected score. Tap a game for a "Why this pick" sheet. |
| **How It Works** | Plain-language explanation of the five systems and the home advantage. |

Ratings, predictions, and method are Jeff Sagarin's; all rights his. This board only presents them.

## Repository layout

```
index.html                              The entire website: styles, markup, data, and script in one file
android/                                Android app that wraps index.html
  app/src/main/java/.../MainActivity.java   Full-screen WebView that loads the bundled board
  app/src/main/res/                     App icon (adaptive + themed), colors, light/dark themes
  app/build.gradle.kts                  Build config; copies ../index.html into the APK at build time
.github/workflows/android-release.yml   Builds the APK and publishes a GitHub Release
docs/app-icon.png                       Icon preview used above
```

### How `index.html` works

The page has no build step, framework, or network requests. It is organized top to bottom as:

1. **`<style>`**: a scoreboard palette defined as CSS variables, with separate light ("paper scorecard") and dark ("chalk on green") themes chosen by the device's color scheme.
2. **Markup**: the header, the five tab panels, and two bottom sheets (team detail and prediction detail).
3. **`var DATA = {...}`**: the week's edition as one JSON object:
   - `editionLabel`, `rawEdition`: which week the numbers cover
   - `homeAdvantage`: points added for the home team, per system
   - `teams[]`: rank, rating, record, schedule strength, and each system's value and rank
   - `conferences[]`: conference averages and ranks
   - `predictions[]`: favorite, underdog, home team, each system's margin, win %, and projected score
4. **Script**: plain JavaScript that renders each tab from `DATA`, handles search, filters, and sorting, and builds the explanation sheets.

### Updating for a new week

Replace the `DATA` object in `index.html` with the new edition's numbers and commit. That one change:

- updates the website (deployed to Netlify from this repo, refreshed every Sunday at noon Central during the season), and
- on `main`, triggers a new Android release carrying the same edition.

## Android app

The app is a thin native wrapper: a single full-screen `WebView` showing the copy of `index.html` bundled in the APK. It needs no internet permission and works offline. It follows the phone's light or dark mode, draws edge to edge under the system bars, closes an open detail sheet on Back, and opens the Sagarin source link in the browser.

- **Requires:** Android 9 (API 28) or newer. Targets Android 16 (API 36).
- **Package:** `com.cfbsaga.ratings`, launcher name "CFB Sagarin".

### Install

1. Open the [latest release](../../releases/latest) on your phone.
2. Download the `cfb-sagarin-<version>.apk` file.
3. Open it and allow installs from your browser or Files app when Android asks.

### Releases

`.github/workflows/android-release.yml` runs when `index.html`, `android/`, or the workflow changes:

| Event | Result |
| --- | --- |
| Pull request | Builds the APK, uploads it as a workflow artifact, and writes the release notes to the job summary. |
| Push to `main` or manual run | All of the above, then publishes release `v1.0.<run number>` with the APK attached. |

Each release's notes list the ratings edition inside the app, the commits since the previous release, and install steps. The version code is the workflow run number, so every release installs as an upgrade.

### Signing (recommended)

Android only installs an update over an existing app when both are signed with the same key. Without signing secrets, the workflow uses each runner's throwaway debug key, so you would need to uninstall before each update. To sign every release with one permanent key, create it once:

```sh
keytool -genkeypair -v -keystore release.jks -alias cfbsagarin \
  -keyalg RSA -keysize 4096 -validity 10000
base64 -w0 release.jks   # macOS: base64 -i release.jks
```

Then add these repository secrets (**Settings > Secrets and variables > Actions**):

| Secret | Value |
| --- | --- |
| `ANDROID_KEYSTORE_BASE64` | The base64 output above |
| `ANDROID_STORE_PASSWORD` | Keystore password |
| `ANDROID_KEY_ALIAS` | `cfbsagarin` (or your alias) |
| `ANDROID_KEY_PASSWORD` | Key password |

Back up `release.jks` and its passwords. If the key is lost, users must uninstall to move to a build signed with a new key. Never commit the keystore.

### Build locally

Requires JDK 17+ and the Android SDK (Android Studio installs both).

```sh
cd android
./gradlew assembleRelease   # APK: app/build/outputs/apk/release/app-release.apk
```

Or open the `android/` folder in Android Studio and run it on a device.
