# FAQ: JC-Mobile SDK Android — API и функции

## Какие категории функций доступны в стандарте PKCS #11?

JC-Mobile SDK Android предоставляет Java-обертку над единой библиотекой PKCS #11 v2.30.

### Служебные функции
- `C.Initialize` — инициализация библиотеки PKCS #11
- `C.Finalize` — завершение работы с библиотекой
- `C.GetInfo` — получение общей информации о библиотеке

### Функции управления слотами и устройствами
- `C.GetSlotList` — получение списка слотов
- `C.GetSlotInfo` — информация о слоте
- `C.GetTokenInfo` — информация о токене
- `C.WaitForSlotEvent` — ожидание события слота (подключение/отключение)
- `C.GetMechanismList` — список поддерживаемых механизмов
- `C.GetMechanismInfo` — информация о механизме
- `C.InitToken` — инициализация токена
- `C.InitPIN` — инициализация PIN-кода
- `C.SetPIN` — изменение PIN-кода

### Функции управления сеансами
- `C.OpenSession` — открытие сессии
- `C.CloseSession` — закрытие сессии
- `C.CloseAllSessions` — закрытие всех сессий
- `C.GetSessionInfo` — информация о сессии
- `C.Login` — аутентификация пользователя (по PIN-коду)
- `C.Logout` — завершение сеанса пользователя

### Функции управления объектами
- `C.CreateObject` — создание объекта
- `C.DestroyObject` — удаление объекта
- `C.GetAttributeValue` — чтение атрибутов объекта
- `C.SetAttributeValue` — установка атрибутов объекта
- `C.FindObjectsInit` — инициализация поиска объектов
- `C.FindObjects` — поиск объектов
- `C.FindObjectsFinal` — завершение поиска объектов

### Криптографические функции
- **Зашифрование:** `C.EncryptInit`, `C.Encrypt`, `C.EncryptUpdate`, `C.EncryptFinal`
- **Расшифрование:** `C.DecryptInit`, `C.Decrypt`, `C.DecryptUpdate`, `C.DecryptFinal`
- **Хэширование:** `C.DigestInit`, `C.Digest`, `C.DigestUpdate`, `C.DigestFinal`
- **Подпись:** `C.SignInit`, `C.Sign`, `C.SignUpdate`, `C.SignFinal`
- **Проверка подписи:** `C.VerifyInit`, `C.Verify`, `C.VerifyUpdate`, `C.VerifyFinal`

### Функции управления ключами
- `C.GenerateKey` — генерация симметричного ключа
- `C.GenerateKeyPair` — генерация ключевой пары
- `C.WrapKey` — экспорт ключа (зашифрование)
- `C.UnwrapKey` — импорт ключа (расшифрование)
- `C.DeriveKey` — выработка производного ключа

### Разное
- `C.GenerateRandom` — генерация случайных данных

## Какие расширенные функции (нестандартные) доступны?

### Служебные расширения
- `Extensions.JC_GetISD` — получение информации о ISD (Issuer Security Domain)
- `Extensions.JC_GetVersionInfo` — получение информации о версии SDK

### PKI-расширение (для апплета Laser)
- `Extensions.pkcs7Sign` / `pkcs7SignEx` — подпись в формате PKCS #7
- `Extensions.pkcs7Verify` / `pkcs7VerifyHW` / `pkcs7TrustedVerifyHW` — проверка подписи PKCS #7
- `Extensions.pkcs7Parse` / `pkcs7ParseEx` — разбор PKCS #7
- `Extensions.createCSR` / `createCSREx` — создание запроса на сертификат (CSR)
- `Extensions.verifyReq` / `verifyReqEx` — проверка запроса на сертификат
- `Extensions.genCert` / `genCertEx` — генерация сертификата
- `Extensions.certVerify` — проверка сертификата
- `Extensions.getCertificateInfo` / `getCertificateInfoEx` — информация о сертификате
- `Extensions.getCertificateAttribute` — получение атрибута сертификата
- `Extensions.checkCertSignature` — проверка подписи сертификата
- `Extensions.JC_CreateCertificateRenewal` / `JC_CreateCertificateRenewal2` — перевыпуск сертификата

### Расширения Криптотокен 2 ЭП
- `Extensions.JC_KT2_ReadExtInfo` — чтение расширенной информации
- `Extensions.JC_KT2_CalcCheckSum` — вычисление контрольной суммы
- `Extensions.JC_KT2_InitToken` — инициализация токена
- `Extensions.JC_KT2_SetSignaturePIN` — установка PIN-кода подписи
- `Extensions.JC_KT2_ChangeSignaturePIN` — смена PIN-кода подписи
- `Extensions.JC_KT2_CreateUnlockChallenge` — создание запроса на разблокировку
- `Extensions.JC_KT2_UnlockWithResponse` — разблокировка по ответу

### Расширения Laser
- `Extensions.JC_PKI_SetComplexity` — установка сложности PIN-кода
- `Extensions.JC_PKI_GetComplexity` — получение параметров сложности PIN
- `Extensions.JC_PKI_WipeCard` — полная очистка карты
- `Extensions.JC_PKI_GetPINInfo` — информация о PIN-коде
- `Extensions.JC_PKI_UnlockUserPIN` — разблокировка PIN пользователя
- `Extensions.JC_PKI_ReadPinCounters` — чтение счетчиков попыток PIN

### Расширения Криптотокен
- `Extensions.JC_CT1_SetAttributeValue` — установка атрибутов

### Разное
- `Extensions.useHardwareHash` — использование аппаратного хэширования
