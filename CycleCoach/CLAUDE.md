# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Build
./gradlew assembleDebug          # Build debug APK
./gradlew assembleRelease        # Build release APK

# Test
./gradlew testDebugUnitTest      # Run unit tests
./gradlew connectedAndroidTest   # Run instrumented tests (requires connected device/emulator)

# Lint
./gradlew lintDebug              # Run lint checks
./gradlew lintFix                # Auto-fix lint issues

# Install
./gradlew installDebug           # Install debug APK on connected device
```

## 1. 📱 Tech Stack
*All dependencies must use the specified libraries and versions unless otherwise agreed.*

*   **Language:** Kotlin 2.0.0+ (Java is **forbidden**).
*   **UI:** Jetpack Compose (2025.03.00+). XML layouts are **forbidden**.
*   **Asynchrony:** Kotlin Coroutines + Flow (RxJava is **forbidden**).
*   **Navigation:** Jetpack Compose Navigation (Fragment Manager is **forbidden**).
*   **DI (Dependency Injection):** Hilt (constructor injection only; field injection is forbidden).
*   **Networking:** Retrofit + Kotlinx Serialization (not Ktor unless specified otherwise).
*   **Database:** Room (with suspend DAOs) + DataStore (SharedPreferences are **forbidden**).
*   **Image Loading:** Coil (version 3.x).
*   **Testing:** JUnit 5, MockK, Turbine (for Flow).

## 2. 🏗️ Architecture and Module Structure

*   **Overall Architecture:** Clean Architecture + MVVM.
*   **Package Structure (multi‑module):**
    *   `:app` — entry point, DI graph.
    *   `:feature:training` — training plan screens.
    *   `:feature:profile` — profile and settings screens.
    *   `:core:data` — repositories (data sources).
    *   `:core:database` — Room DAOs and Entities.
    *   `:core:network` — API interfaces and network models.
    *   `:core:model` — domain models.
    *   `:core:ui` — reusable UI components and themes.
*   **Layer Rules:**
    *   **UI (Presentation):** One ViewModel per screen, named `{Screen}ViewModel`. Screen state is described with a **sealed class `UiState`**.
    *   **Domain:** UseCases are classes with a single public `operator fun invoke()`. Repositories reside in `:core:data`; their interfaces are defined either there or in `:core:model`.
    *   **Data:** Repositories work with `Flow` and implement an **offline‑first** approach (first data from the database, then network updates).


## 3. ✍️ Code Style and Conventions

*   **Naming:** Classes — `PascalCase`, functions/variables — `camelCase`, constants (`companion object`) — `UPPER_SNAKE_CASE`.
*   **Null safety:** The `!!` operator is **forbidden** in production code. Use `?:`, `?.`, or explicit checks.
*   **Immutability:** Prefer `val` over `var` whenever possible.
*   **Formatting:** Line length up to 120 characters, function length up to 30 lines (as a guideline).

## 4. 🚫 Forbidden Patterns

*   ❌ **Strictly forbidden:** Using `LiveData`. Only `StateFlow` / `SharedFlow`.
*   ❌ **Forbidden:** Direct access to the database or API from a ViewModel. Always go through UseCase/Repository.
*   ❌ **Forbidden:** Hardcoding API keys or URLs. Use `BuildConfig` and `gradle.properties`.
*   ❌ **Forbidden:** Using `Thread.sleep()`. Only `delay()` in coroutines.

**SDK targets**: min SDK 29, target/compile SDK 36.

**Dependency versions** are managed via Gradle version catalog at `gradle/libs.versions.toml`.
