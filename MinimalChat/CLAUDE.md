# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build Commands

```bash
# Build the project
./gradlew build

# Assemble debug APK
./gradlew assembleDebug

# Assemble release APK
./gradlew assembleRelease

# Run unit tests (JVM)
./gradlew test

# Run a single unit test class
./gradlew test --tests "ru.yar.minimalchat.ExampleUnitTest"

# Run instrumented tests (requires device/emulator)
./gradlew connectedAndroidTest

# Install debug build on connected device
./gradlew installDebug
```

## Architecture

This is a minimal Android application built with Jetpack Compose and Material3.

- **Package**: `ru.yar.minimalchat`
- **Min SDK**: 29, **Target/Compile SDK**: 36
- **Single Activity**: `MainActivity` extends `ComponentActivity`, uses `enableEdgeToEdge()` and Compose `Scaffold`
- **UI layer**: All UI is in Jetpack Compose. Theme is in `ui/theme/` (Color.kt, Theme.kt, Type.kt)
- **`MinimalChatTheme`** supports dynamic color (Material You on Android 12+) and auto dark/light switching

## Key Libraries

Dependencies are managed via a version catalog at `gradle/libs.versions.toml`:
- Kotlin 2.2.10, AGP 9.1.0
- Compose BOM 2024.09.00 with Material3
- `androidx.activity:activity-compose` 1.8.0
- `androidx.lifecycle:lifecycle-runtime-ktx` 2.6.1
