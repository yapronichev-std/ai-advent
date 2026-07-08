# FAQ: JC-Mobile SDK Android — Интеграция в приложение

## Какие библиотеки входят в состав SDK?

### Каталог libs

**Java-библиотеки (.jar):**
- `jcPKCS11-2.jar` — Java-обертка над единой библиотекой PKCS #11
- `jna-min.jar` — библиотека, обеспечивающая механизм JNA (Java Native Access)

**Нативные библиотеки (.so):**
- `libjcPKCS11-2.so` — нативная реализация PKCS #11
- `libgti_jni.so` — библиотека GTI JNI
- `libjnidispatch.so` — диспетчер JNA
- `libjcpcsclite.so` — библиотека PC/SC Lite

Архитектуры:
- `arm64-v8a` — для 64-битных устройств Android
- `armeabi-v7a` — для 32-битных устройств Android

### Каталог sources

Содержит примеры работы с апплетами:
- `GOST2_*` — примеры для апплета Криптотокен 2 ЭП
- `PKI_*` — примеры для апплета Laser
- `GOST_*` — примеры для апплета Криптотокен
- `LICENSE_*` — примеры для апплета Лицензионный

## Как интегрировать SDK в Android Studio проект?

### Шаг 1: Копирование библиотек
1. В папке `app` проекта создать папку `libs` (если её нет)
2. Скопировать в `libs` файлы: `jcPKCS11-2.jar`, `jna-min.jar`

### Шаг 2: Копирование нативных библиотек
1. Перейти в `app/src/main`
2. Создать папку `jniLibs` (если её нет)
3. Скопировать в `jniLibs` папки `arm64-v8a` и `armeabi-v7a` (содержащие .so файлы)

### Шаг 3: Подключение в Android Studio
1. Нажать **File → Project Structure**
2. Перейти во вкладку **Dependencies**
3. Нажать **+ → JAR/AAR Dependency**
4. В поле Step 1 ввести `libs` и нажать OK

### Шаг 4: Установка JaCarta Service
Установить приложение **JaCarta Service** из Google Play на тестовое устройство.

## Какова финальная файловая структура проекта?

```
project/
├── app/
│   ├── libs/
│   │   ├── jcPKCS11-2.jar
│   │   └── jna-min.jar
│   ├── src/
│   │   └── main/
│   │       └── jniLibs/
│   │           ├── arm64-v8a/
│   │           │   ├── libjcPKCS11-2.so
│   │           │   ├── libgti_jni.so
│   │           │   ├── libjnidispatch.so
│   │           │   └── libjcpcsclite.so
│   │           └── armeabi-v7a/
│   │               ├── libjcPKCS11-2.so
│   │               ├── libgti_jni.so
│   │               ├── libjnidispatch.so
│   │               └── libjcpcsclite.so
```

## Как администрировать смарт-карты JaCarta?

Для администрирования смарт-карт JaCarta ГОСТ, JaCarta PKI и JaCarta PKI/ГОСТ используйте **ПК Единый Клиент JaCarta**, установленный на ПК (не на мобильном устройстве).

## Как собрать примеры из SDK?

### Сборка через CLI (командную строку)

1. Установить **JDK 11**
2. Установить **Android SDK**
3. Задать переменные среды для Gradle:
   ```bash
   export ANDROID_SDK_ROOT="/Users/username/Library/android/android-sdk"
   ```
4. Собрать компонент `common.jar`:
   ```bash
   cd common
   ./gradlew makeJar
   # Результат: common.jar в папке libs
   ```
5. Собрать нужный пример:
   ```bash
   cd sources/GOST2_info
   ./gradlew :app:assembleDebug
   # Результат: app-debug.apk в app/build/outputs/apk/debug
   ```

### Сборка через Android Studio (IDE)

1. Установить Android Studio (Android SDK установится автоматически)
2. **Важно:** папки `libs` и `sources` должны находиться в одной директории
3. Открыть проект `common` → собрать `common.jar` (зеленая стрелка рядом с задачей `makeJar`)
4. Открыть интересующий пример: File → Open → выбрать проект из `sources/`
5. Подключить смартфон с включенной отладкой по USB (режим разработчика, установка по USB)
6. Запустить пример: зеленая стрелка или **Shift+F10**
